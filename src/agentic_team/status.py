"""Status polling and formatting for team workers."""

from __future__ import annotations

import re
import warnings
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    STATE_DIR,
    TeamConfig,
    WorkerState,
    load_workers,
    save_workers,
)
from .tmux import EXIT_SENTINEL, TmuxOrchestrator


PROMPT_DELIVERY_TIMEOUT_SECONDS = 30
_EXIT_RE = re.compile(re.escape(EXIT_SENTINEL) + r"(?P<code>\d+)")
_COMMAND_NOT_FOUND_RE = re.compile(r"command not found", re.IGNORECASE)


def get_team_status(config: TeamConfig) -> dict:
    """Check the status of all workers, updating state as needed.

    Returns a dict with team info and worker statuses.
    """
    tmux = TmuxOrchestrator(config.tmux_session)
    workers = load_workers(config.name)
    windows = {w.name: w for w in tmux.list_windows()}
    state_dir = STATE_DIR / config.name
    updated = False

    # In multi mode, workers are joined into the host window — their
    # original window names won't appear in list-windows.  Track which
    # workers are joined so we don't falsely mark them as done.
    multi_file = state_dir / "multi_targets"
    multi_joined: set[str] = set()
    if multi_file.exists():
        multi_joined = set(multi_file.read_text().strip().splitlines())

    # Deliver any pending prompts to interactive workers that are now ready
    delivered = tmux.deliver_pending_prompts(state_dir)
    if delivered:
        updated = True

    # Check which workers still have pending (undelivered) prompts —
    # they haven't started working yet, so skip idle detection for them.
    pending_dir = state_dir / "pending_prompts"
    pending_workers: set[str] = set()
    if pending_dir.exists():
        pending_workers = {f.name for f in pending_dir.iterdir()}

    for worker in workers:
        prompt_file = pending_dir / worker.name

        # Re-evaluate interactive workers previously marked "done" —
        # their pane persists and they may be working on a new task.
        if worker.mode == "interactive" and worker.status == "done":
            in_windows = (
                worker.tmux_window in windows
                or worker.tmux_window in multi_joined
            )
            if in_windows and not tmux.is_pane_dead(worker.tmux_window, state_dir=state_dir):
                if _is_waiting_for_input(worker, tmux, state_dir):
                    worker.status = "waiting"
                    updated = True
                elif not _is_interactive_idle(worker, tmux, state_dir):
                    updated = _set_worker_running(worker) or updated
            continue

        if worker.status not in ("running", "waiting"):
            continue

        in_windows = (
            worker.tmux_window in windows
            or worker.tmux_window in multi_joined
        )

        captured = None
        if in_windows:
            captured = tmux.capture_pane_safe(
                worker.tmux_window,
                lines=80,
                state_dir=state_dir,
                context=f"checking worker {worker.name}",
            )

        exit_code = _extract_exit_code(captured)
        if worker.mode == "interactive" and exit_code is not None:
            updated = _set_worker_error(
                worker,
                _describe_exit(captured or "", exit_code, interactive=True),
                exit_code,
            ) or updated
            _cleanup_pending_prompt(prompt_file)
            continue

        if worker.mode == "oneshot" and exit_code is not None:
            if exit_code == 0:
                updated = _set_worker_done(worker, exit_code=exit_code) or updated
                _try_extract_session_id(config, worker)
            else:
                updated = _set_worker_error(
                    worker,
                    _describe_exit(captured or "", exit_code),
                    exit_code,
                ) or updated
            continue

        # Check if the tmux window still exists.
        # Skip this check for workers joined into a multi-pane layout —
        # their windows were merged into the host window.
        if not in_windows:
            updated = _set_worker_error(
                worker,
                "tmux window disappeared while the worker was still running",
            ) or updated
            continue

        # Check if the pane process has exited
        if tmux.is_pane_dead(worker.tmux_window, state_dir=state_dir):
            updated = _set_worker_error(
                worker,
                "tmux pane exited unexpectedly while the worker was still running",
            ) or updated
            continue

        # Check if the worker is blocked waiting for user confirmation
        if _is_waiting_for_input(worker, tmux, state_dir):
            if worker.status != "waiting":
                worker.status = "waiting"
                updated = True
            continue

        # If previously waiting but no longer blocked, resume running
        if worker.status == "waiting":
            worker.status = "running"
            updated = True

        # For oneshot workers, the pane stays alive (drops to shell) after
        # the agent command finishes. Detect completion by checking the
        # capture-pane output for a shell prompt or JSON result.
        if worker.mode == "oneshot" and _is_oneshot_done(config, worker, tmux, state_dir):
            updated = _set_worker_done(worker, exit_code=0) or updated
            _try_extract_session_id(config, worker)

        # For interactive workers, the agent stays running but returns to
        # its input prompt (❯) after completing a task. Detect "idle" state.
        # Skip if the worker's initial prompt hasn't been delivered yet.
        if worker.mode == "interactive" and prompt_file.exists():
            if _prompt_delivery_timed_out(prompt_file):
                updated = _set_worker_error(
                    worker,
                    f"initial prompt was not delivered within {PROMPT_DELIVERY_TIMEOUT_SECONDS}s",
                ) or updated
                _cleanup_pending_prompt(prompt_file)
            continue

        if (
            worker.mode == "interactive"
            and worker.name not in pending_workers
            and _is_interactive_idle(worker, tmux, state_dir)
        ):
            updated = _set_worker_done(worker) or updated

    if updated:
        save_workers(config.name, workers)

    # Build status dict
    lead_active = "lead" in windows
    now = datetime.now(timezone.utc)

    worker_statuses = []
    for w in workers:
        elapsed = ""
        if w.started_at:
            try:
                started = datetime.fromisoformat(w.started_at)
                delta = now - started
                minutes = int(delta.total_seconds() // 60)
                seconds = int(delta.total_seconds() % 60)
                elapsed = f"{minutes}m {seconds:02d}s"
            except ValueError:
                pass

        worker_statuses.append({
            "name": w.name,
            "provider": w.provider,
            "mode": w.mode,
            "status": w.status,
            "task": w.task,
            "source": getattr(w, "source", "cli"),
            "elapsed": elapsed,
            "last_error": w.last_error,
            "exit_code": w.exit_code,
        })

    return {
        "team": config.name,
        "session": config.tmux_session,
        "lead_active": lead_active,
        "workers": worker_statuses,
    }


def format_status(status: dict) -> None:
    """Pretty-print the team status using rich."""
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    console = Console()

    # Header
    lead_style = "green" if status["lead_active"] else "red"
    lead_label = "active" if status["lead_active"] else "inactive"
    header = Text()
    header.append(f"Team: {status['team']}", style="bold")
    header.append(f"  (session: {status['session']})  Lead: ")
    header.append(lead_label, style=lead_style)
    console.print(header)

    workers = status["workers"]
    if not workers:
        console.print("\nNo workers.", style="dim")
        return

    table = Table(title=f"Workers ({len(workers)})", title_style="bold", show_edge=False, pad_edge=False)
    table.add_column("Name", style="cyan")
    table.add_column("Provider", style="dim")
    table.add_column("Status")
    table.add_column("Elapsed", justify="right", style="dim")
    table.add_column("Task")
    table.add_column("Error", style="red")

    status_styles = {
        "running": "bold yellow",
        "waiting": "bold magenta",
        "done": "bold green",
        "error": "bold red",
        "pending": "dim",
    }

    source_styles = {
        "cli": "bright_blue",
        "file": "magenta",
        "lead": "bright_yellow",
    }

    for w in workers:
        style = status_styles.get(w["status"], "")
        task_text = w["task"]
        if len(task_text) > 55:
            task_text = task_text[:52] + "..."
        source = w.get("source", "cli")
        task_col = Text()
        task_col.append(f"[{source}] ", style=source_styles.get(source, "dim"))
        task_col.append(task_text)
        error_text = ""
        if w.get("last_error"):
            error_text = w["last_error"]
            if w.get("exit_code") is not None:
                error_text = f"{error_text} (exit {w['exit_code']})"
        table.add_row(
            w["name"],
            w["provider"],
            Text(w["status"], style=style),
            w["elapsed"],
            task_col,
            error_text,
        )

    console.print(table)


def _is_oneshot_done(
    config: TeamConfig, worker: WorkerState, tmux: TmuxOrchestrator,
    state_dir: Path | None = None,
) -> bool:
    """Detect if a oneshot worker's command has finished.

    The pane stays alive (drops back to shell) after the agent exits.
    We find the LAST agent command invocation in the pane, then check
    if there's a completion signal (JSON result or shell prompt) after it.
    This avoids false positives from previous runs' output still visible
    in scrollback.
    """
    output = tmux.capture_pane_safe(
        worker.tmux_window,
        lines=80,
        state_dir=state_dir,
        context=f"checking oneshot completion for {worker.name}",
    )
    if output is None:
        return False

    lines = output.splitlines()

    # Find the index of the LAST agent command invocation
    # (the line starting with ❯ or $ followed by the agent CLI)
    agent_cmds = ("claude ", "codex ", "gemini ")
    last_cmd_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        for cmd in agent_cmds:
            if cmd in stripped:
                last_cmd_idx = i
                break
        if last_cmd_idx >= 0:
            break

    if last_cmd_idx < 0:
        return False  # Haven't even seen the command yet

    # Only look at lines AFTER the last command invocation
    after_cmd = "\n".join(lines[last_cmd_idx + 1:])
    after_lines = [l for l in lines[last_cmd_idx + 1:] if l.strip()]

    # Method 1: Check for claude JSON result after the last command
    if worker.provider == "claude" and '"type":"result"' in after_cmd:
        return True

    # Method 1b: Explicit exit sentinel from the wrapped shell command
    if _extract_exit_code(after_cmd) == 0:
        return True

    # Method 2: Check for a shell prompt after command output
    # A prompt means the command exited and the shell is waiting
    for line in after_lines:
        stripped = line.strip()
        if (
            "\u276f" in stripped  # ❯ (powerlevel10k)
            or stripped.endswith("$")
            or stripped.endswith("%")
            or stripped.endswith("#")
        ):
            return True

    return False



def _is_interactive_idle(
    worker: WorkerState, tmux: TmuxOrchestrator,
    state_dir: Path | None = None,
) -> bool:
    """Detect if an interactive worker has finished its task and is idle.

    Uses capture_pane for all providers — TUI agents rewrite the screen
    so log files don't reliably reflect the current state. capture_pane
    gives the actual rendered screen content.

    Provider-specific signals:
    - Claude: "esc to inter(rupt)" absent from tail + output markers present
    - Codex: "Worked for" summary or idle prompt "›" visible
    - Gemini: "Type your message" idle prompt visible
    """
    raw = tmux.capture_pane_safe(
        worker.tmux_window,
        lines=30,
        state_dir=state_dir,
        context=f"checking interactive idleness for {worker.name}",
    )
    if raw is None:
        return False

    # Strip trailing blank lines — TUI apps often pad the bottom of the
    # pane, which pushes status/prompt indicators out of the tail window.
    output = raw.rstrip()

    if worker.provider == "claude":
        tail = "\n".join(output.splitlines()[-10:])
        if "esc to inter" in tail:
            return False
        # Not actively working. Confirm the agent has been active by
        # checking for substantial content (excludes empty/startup panes).
        # We can't rely on ⏺/⎿ markers — they scroll out of view for
        # long responses. The ❯ prompt + no "esc to interrupt" is enough.
        content_lines = [l for l in output.splitlines() if l.strip()]
        if len(content_lines) > 5:
            return True

    elif worker.provider == "codex":
        # If "Working (" is visible, the agent is actively processing.
        if "Working (" in output:
            return False
        # Don't report idle if the agent is waiting for user confirmation —
        # the confirmation menu contains "›" which looks like the idle prompt.
        if "Press enter to confirm" in output or "Would you like to run" in output:
            return False
        # "Worked for" summary means task completed.
        if "Worked for" in output:
            return True
        # Idle: "›" prompt visible with no working indicator.
        # The "›" line or "Use /skills" appears when Codex is waiting.
        tail_lines = [l.strip() for l in output.splitlines() if l.strip()]
        if tail_lines and any(
            l.startswith("\u203a") or "Use /skills" in l
            for l in tail_lines[-5:]
        ):
            return True

    elif worker.provider == "gemini":
        # "Type your message" appears when idle. Guard against startup
        # by requiring substantial pane content (agent produced output).
        tail = "\n".join(output.splitlines()[-10:])
        if "Type your message" in tail:
            content_lines = [l for l in output.splitlines() if l.strip()]
            if len(content_lines) > 10:
                return True

    return False


def _is_waiting_for_input(
    worker: WorkerState, tmux: TmuxOrchestrator,
    state_dir: Path | None = None,
) -> bool:
    """Detect if a worker is blocked waiting for user confirmation.

    Provider-specific signals:
    - Claude: "approve" / "deny" / "(Y/n)" / "(y/N)" in the tail
    - Codex: "Would you like to run" / "Yes, proceed" / "Press enter to confirm"
    - Gemini: "Do you want to" / "[Y/n]" prompts
    """
    try:
        raw = tmux.capture_pane(
            worker.tmux_window, lines=20, state_dir=state_dir,
        )
    except Exception:
        return False

    tail = raw.rstrip()
    tail_lines = tail.splitlines()[-15:]
    tail_text = "\n".join(tail_lines)

    if worker.provider == "claude":
        # Claude Code shows "approve" / "deny" or "(Y/n)" permission prompts
        # But NOT when "esc to inter" is visible (that means it's working)
        if "esc to inter" in tail_text:
            return False
        indicators = ("(Y/n)", "(y/N)", "approve", "deny")
        return any(ind in tail_text for ind in indicators)

    elif worker.provider == "codex":
        # Codex shows a numbered menu with "Yes, proceed" or
        # "Would you like to run" / "Press enter to confirm"
        indicators = (
            "Would you like to run",
            "Yes, proceed",
            "Press enter to confirm",
            "esc to cancel",
        )
        return any(ind in tail_text for ind in indicators)

    elif worker.provider == "gemini":
        indicators = ("Do you want to", "[Y/n]", "[y/N]")
        return any(ind in tail_text for ind in indicators)

    return False


def _try_extract_session_id(config: TeamConfig, worker: WorkerState) -> None:
    """Try to parse session_id from claude oneshot output.

    Uses capture-pane text (clean) rather than raw pipe-pane logs
    (full of escape codes). The JSON output may wrap across multiple
    lines in the pane, so we concatenate and search for session_id.
    """
    if worker.provider != "claude" or worker.mode != "oneshot":
        return

    # Try capture-pane first (clean text, may be wrapped across lines)
    tmux = TmuxOrchestrator(config.tmux_session)
    output = tmux.capture_pane_safe(
        worker.tmux_window,
        lines=80,
        context=f"extracting session id for {worker.name}",
    )
    if output is None:
        return

    # Find the last agent command and only search after it
    lines = output.splitlines()
    last_cmd_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if "claude " in lines[i]:
            last_cmd_idx = i
            break

    # Join lines after the last command (no separators so wrapped UUIDs reassemble)
    after = lines[last_cmd_idx + 1:] if last_cmd_idx >= 0 else lines
    flat = "".join(after)
    m = re.search(r'"session_id":"([a-f0-9-]+)"', flat)
    if m:
        worker.session_id = m.group(1)


def _extract_exit_code(output: str | None) -> int | None:
    """Extract the most recent wrapped shell exit sentinel from pane output."""
    if not output:
        return None
    matches = list(_EXIT_RE.finditer(output))
    if not matches:
        return None
    return int(matches[-1].group("code"))


def _describe_exit(output: str, exit_code: int, interactive: bool = False) -> str:
    """Turn an exit code and pane output into a concise persisted error."""
    if _COMMAND_NOT_FOUND_RE.search(output) or exit_code == 127:
        return "agent command not found on PATH"

    lines = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(EXIT_SENTINEL):
            continue
        if _looks_like_shell_prompt(stripped):
            continue
        lines.append(stripped)

    if lines:
        tail = lines[-1]
        if "error" in tail.lower() or interactive:
            return tail

    if interactive:
        return f"interactive worker exited before accepting prompts (exit {exit_code})"
    return f"worker exited with status {exit_code}"


def _looks_like_shell_prompt(stripped: str) -> bool:
    """Heuristic prompt detection for shell and TUI agent prompts."""
    return (
        "\u276f" in stripped
        or stripped.endswith("$")
        or stripped.endswith("%")
        or stripped.endswith("#")
    )


def _prompt_delivery_timed_out(prompt_file: Path) -> bool:
    """Return True once a queued prompt has aged past the delivery budget."""
    try:
        age_seconds = datetime.now(timezone.utc).timestamp() - prompt_file.stat().st_mtime
    except OSError as exc:
        warnings.warn(
            f"Could not inspect pending prompt {prompt_file}: {exc}",
            stacklevel=2,
        )
        return False
    return age_seconds >= PROMPT_DELIVERY_TIMEOUT_SECONDS


def _cleanup_pending_prompt(prompt_file: Path) -> None:
    """Remove a stale pending prompt file after a worker has errored."""
    try:
        prompt_file.unlink(missing_ok=True)
    except OSError as exc:
        warnings.warn(
            f"Could not remove pending prompt {prompt_file}: {exc}",
            stacklevel=2,
        )


def _set_worker_running(worker: WorkerState) -> bool:
    """Transition a worker back to running and clear stale failure state."""
    changed = (
        worker.status != "running"
        or worker.last_error is not None
        or worker.exit_code is not None
    )
    worker.status = "running"
    worker.last_error = None
    worker.exit_code = None
    return changed


def _set_worker_done(worker: WorkerState, exit_code: int | None = None) -> bool:
    """Mark a worker done and clear any prior error detail."""
    changed = (
        worker.status != "done"
        or worker.last_error is not None
        or worker.exit_code != exit_code
    )
    worker.status = "done"
    worker.last_error = None
    worker.exit_code = exit_code
    return changed


def _set_worker_error(
    worker: WorkerState, last_error: str, exit_code: int | None = None,
) -> bool:
    """Mark a worker as failed with persisted diagnostic detail."""
    changed = (
        worker.status != "error"
        or worker.last_error != last_error
        or worker.exit_code != exit_code
    )
    worker.status = "error"
    worker.last_error = last_error
    worker.exit_code = exit_code
    return changed
