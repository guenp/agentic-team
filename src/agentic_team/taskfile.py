"""Parse and update markdown task files with checkbox syntax.

Format:
    ## ~/repos/backend          ← sets working_dir for tasks below
    - [ ] Fix the login bug     ← pending task
    - [x] Already done          ← skipped on load
    - [ ] Do thing (provider: codex, mode: interactive)  ← inline overrides

Supported inline overrides: provider, mode, model, name
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import _atomic_write_bytes as _atomic_write_bytes_impl

# Matches: - [ ] task text (key: val, key: val)
_CHECKBOX_RE = re.compile(
    r"^(\s*)-\s*\[([ xX])\]\s+(.+)$"
)

# Matches: (key: value, key: value) at end of line
_OVERRIDES_RE = re.compile(
    r"\(([^)]+)\)\s*$"
)

# Matches: ← worker info appended by writeback
_WRITEBACK_RE = re.compile(
    r"\s*←.*$"
)

# Extracts worker name from ← annotation
_ANNOTATION_RE = re.compile(
    r"←\s*(\S+)"
)


class TaskFileError(RuntimeError):
    """Raised when a markdown task file cannot be read or updated safely."""


@dataclass
class TaskEntry:
    """A single task parsed from a markdown file."""

    task: str
    done: bool = False
    working_dir: str | None = None
    provider: str | None = None
    mode: str | None = None
    model: str | None = None
    name: str | None = None
    line_number: int = 0  # 0-indexed line in the source file
    indent: str = ""

    # Populated after spawning
    worker_name: str | None = None
    worker_status: str | None = None
    elapsed: str | None = None


def _read_task_text(path: Path) -> str:
    """Read a task file with recovery guidance on I/O failure."""
    try:
        return path.read_text()
    except OSError as exc:
        raise TaskFileError(
            f"Could not read task file at {path}: {exc}. "
            f"Check permissions or restore the file, then retry."
        ) from exc


def _atomic_write_text(path: Path, text: str, description: str) -> None:
    """Write task files atomically to avoid partial updates."""
    from .config import StateFileError

    try:
        _atomic_write_bytes_impl(path, text.encode(), description)
    except StateFileError as exc:
        raise TaskFileError(str(exc)) from exc


def parse_task_file(path: Path) -> list[TaskEntry]:
    """Parse a markdown task file into TaskEntry objects.

    Headings (## ...) set the working_dir context for subsequent tasks.
    Only unchecked (- [ ]) tasks are returned with done=False.
    Checked (- [x]) tasks are returned with done=True.
    """
    text = _read_task_text(path)
    lines = text.splitlines()
    tasks: list[TaskEntry] = []
    current_dir: str | None = None

    for i, line in enumerate(lines):
        # Check for heading -> working_dir context
        stripped = line.strip()
        if stripped.startswith("## "):
            dir_path = stripped[3:].strip()
            # Expand ~ in the heading
            if dir_path.startswith("~"):
                dir_path = str(Path(dir_path).expanduser())
            current_dir = dir_path
            continue

        # Check for checkbox line
        m = _CHECKBOX_RE.match(line)
        if not m:
            continue

        indent = m.group(1)
        check = m.group(2)
        raw_text = m.group(3)
        done = check.lower() == "x"

        # Extract worker name from annotation before stripping it
        annotated_worker: str | None = None
        am = _ANNOTATION_RE.search(raw_text)
        if am:
            annotated_worker = am.group(1)

        # Strip any previous writeback annotation
        raw_text = _WRITEBACK_RE.sub("", raw_text).strip()

        # Extract inline overrides
        overrides: dict[str, str] = {}
        om = _OVERRIDES_RE.search(raw_text)
        if om:
            raw_text = raw_text[: om.start()].strip()
            for pair in om.group(1).split(","):
                pair = pair.strip()
                if ":" in pair:
                    k, v = pair.split(":", 1)
                    overrides[k.strip().lower()] = v.strip()

        entry = TaskEntry(
            task=raw_text,
            done=done,
            working_dir=overrides.pop("working_dir", None) or overrides.pop("dir", None) or current_dir,
            provider=overrides.pop("provider", None),
            mode=overrides.pop("mode", None),
            model=overrides.pop("model", None),
            name=overrides.pop("name", None),
            line_number=i,
            indent=indent,
            worker_name=annotated_worker,
        )
        tasks.append(entry)

    return tasks


def pending_tasks(path: Path) -> list[TaskEntry]:
    """Return only unchecked tasks from a task file."""
    return [t for t in parse_task_file(path) if not t.done]


def update_task_file(path: Path, updates: dict[int, TaskEntry]) -> None:
    """Write back status updates to the markdown task file.

    Args:
        path: Path to the task file.
        updates: Mapping of line_number -> TaskEntry with updated fields.
            If entry.done is True, the checkbox is ticked.
            If entry.worker_name is set, a ← annotation is appended.
    """
    lines = _read_task_text(path).splitlines()

    for line_num, entry in updates.items():
        if line_num >= len(lines):
            continue

        line = lines[line_num]
        m = _CHECKBOX_RE.match(line)
        if not m:
            continue

        indent = m.group(1)
        raw_text = m.group(3)

        # Strip old writeback
        raw_text = _WRITEBACK_RE.sub("", raw_text).strip()

        # Update checkbox
        check = "x" if entry.done else " "

        # Build annotation
        annotation = ""
        if entry.worker_name:
            parts = [entry.worker_name]
            if entry.worker_status:
                parts.append(entry.worker_status)
            if entry.elapsed:
                parts.append(entry.elapsed)
            annotation = f" \u2190 {' | '.join(parts)}"

        lines[line_num] = f"{indent}- [{check}] {raw_text}{annotation}"

    _atomic_write_text(path, "\n".join(lines) + "\n", "task file")
