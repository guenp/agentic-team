"""Status polling and formatting for team workers."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    STATE_DIR,
    TeamConfig,
    WorkerState,
    load_workers,
    log_dir_for_team,
    save_workers,
)
from .tmux import TmuxOrchestrator


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
    log_dir = log_dir_for_team(config.name)
    delivered = tmux.deliver_pending_prompts(log_dir)
    if delivered:
        updated = True

    for worker in workers:
        if worker.status != "running":
            continue

        # Check if the tmux window still exists.
        # Skip this check for workers joined into a multi-pane layout —
        # their windows were merged into the host window.
        if worker.tmux_window not in windows and worker.tmux_window not in multi_joined:
            worker.status = "done"
            updated = True
            _try_extract_session_id(config, worker)
            continue

        # Check if the pane process has exited
        if tmux.is_pane_dead(worker.tmux_window, state_dir=state_dir):
            worker.status = "done"
            updated = True
            _try_extract_session_id(config, worker)
            continue

        # For oneshot workers, the pane stays alive (drops to shell) after
        # the agent command finishes. Detect completion by checking the
        # capture-pane output for a shell prompt or JSON result.
        if worker.mode == "oneshot" and _is_oneshot_done(config, worker, tmux, state_dir):
            worker.status = "done"
            updated = True
            _try_extract_session_id(config, worker)

        # For interactive workers, the agent stays running but returns to
        # its input prompt (❯) after completing a task. Detect "idle" state.
        if worker.mode == "interactive" and _is_interactive_idle(worker, tmux, state_dir):
            worker.status = "done"
            updated = True

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
            "elapsed": elapsed,
        })

    return {
        "team": config.name,
        "session": config.tmux_session,
        "lead_active": lead_active,
        "workers": worker_statuses,
    }


def format_status(status: dict) -> str:
    """Pretty-print the team status."""
    lines: list[str] = []
    lines.append(f"Team: {status['team']} (session: {status['session']})")

    lead_str = "active" if status["lead_active"] else "inactive"
    lines.append(f"Lead: {lead_str}")

    workers = status["workers"]
    if not workers:
        lines.append("\nNo workers.")
    else:
        lines.append(f"\nWorkers ({len(workers)}):")
        # Column widths
        max_name = max(len(w["name"]) for w in workers)
        max_prov = max(len(w["provider"]) for w in workers)
        for w in workers:
            name = w["name"].ljust(max_name)
            prov = w["provider"].ljust(max_prov)
            mode = w["mode"].ljust(11)
            stat = w["status"].ljust(7)
            elapsed = w["elapsed"]
            task = w["task"]
            if len(task) > 50:
                task = task[:47] + "..."
            line = f"  {name}  {prov}  {mode}  {stat}  {elapsed:>10}  {task}"
            lines.append(line)

    return "\n".join(lines)


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
    try:
        output = tmux.capture_pane(worker.tmux_window, lines=80, state_dir=state_dir)
    except Exception:
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


_ANSI_RE = re.compile(
    r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][\x20-\x7e]*(?:\x07|\x1b\\)|\x1b[()][0-9A-Z]"
)


def _read_log_tail(worker_name: str, state_dir: Path | None, size: int = 8192) -> str | None:
    """Read and clean the tail of a worker's pipe-pane log file."""
    if not state_dir:
        return None
    team_name = state_dir.name
    log_path = log_dir_for_team(team_name) / f"{worker_name}.log"
    if not log_path.exists():
        return None
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            file_size = f.tell()
            if file_size < 1024:
                return None  # Too small — agent probably hasn't started
            f.seek(max(0, file_size - size))
            raw = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    return _ANSI_RE.sub("", raw).replace("\r", "")


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
    try:
        output = tmux.capture_pane(
            worker.tmux_window, lines=30, state_dir=state_dir,
        )
    except Exception:
        return False

    if worker.provider == "claude":
        tail = "\n".join(output.splitlines()[-10:])
        if "esc to inter" in tail:
            return False
        # Confirm the agent actually produced output.
        if "\u23fa" in output or "⎿" in output:
            return True

    elif worker.provider == "codex":
        # Codex shows "Worked for Xm Ys" when done, or an idle prompt
        # "›" with a status line showing model/usage info.
        if "Worked for" in output:
            return True
        # Idle prompt: last non-empty lines show "›" and model info
        tail_lines = [l.strip() for l in output.splitlines() if l.strip()]
        if tail_lines:
            last = tail_lines[-1]
            # Status line like "gpt-5.4 xhigh · 79% left"
            if "% left" in last or "left ·" in last:
                return True

    elif worker.provider == "gemini":
        tail = "\n".join(output.splitlines()[-10:])
        if "Type your message" in tail:
            return True

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
    try:
        tmux = TmuxOrchestrator(config.tmux_session)
        output = tmux.capture_pane(worker.tmux_window, lines=80)
    except Exception:
        return

    # Find the last agent command and only search after it
    lines = output.splitlines()
    last_cmd_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if "claude " in lines[i]:
            last_cmd_idx = i
            break

    # Join lines after the last command (no separators so wrapped UUIDs reassemble)
    import re
    after = lines[last_cmd_idx + 1:] if last_cmd_idx >= 0 else lines
    flat = "".join(after)
    m = re.search(r'"session_id":"([a-f0-9-]+)"', flat)
    if m:
        worker.session_id = m.group(1)
