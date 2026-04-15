"""Status polling and formatting for team workers."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .config import (
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
    updated = False

    # Deliver any pending prompts to interactive workers that are now ready
    log_dir = log_dir_for_team(config.name)
    delivered = tmux.deliver_pending_prompts(log_dir)
    if delivered:
        updated = True

    for worker in workers:
        if worker.status != "running":
            continue

        # Check if the tmux window still exists
        if worker.tmux_window not in windows:
            worker.status = "done"
            updated = True
            _try_extract_session_id(config, worker)
            continue

        # Check if the pane process has exited
        if tmux.is_pane_dead(worker.tmux_window):
            worker.status = "done"
            updated = True
            _try_extract_session_id(config, worker)
            continue

        # For oneshot workers, the pane stays alive (drops to shell) after
        # the agent command finishes. Detect completion by checking the
        # capture-pane output for a shell prompt or JSON result.
        if worker.mode == "oneshot" and _is_oneshot_done(config, worker, tmux):
            worker.status = "done"
            updated = True
            _try_extract_session_id(config, worker)

        # For interactive workers, the agent stays running but returns to
        # its input prompt (❯) after completing a task. Detect "idle" state.
        if worker.mode == "interactive" and _is_interactive_idle(worker, tmux):
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
    config: TeamConfig, worker: WorkerState, tmux: TmuxOrchestrator
) -> bool:
    """Detect if a oneshot worker's command has finished.

    The pane stays alive (drops back to shell) after the agent exits.
    We find the LAST agent command invocation in the pane, then check
    if there's a completion signal (JSON result or shell prompt) after it.
    This avoids false positives from previous runs' output still visible
    in scrollback.
    """
    try:
        output = tmux.capture_pane(worker.tmux_window, lines=80)
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


def _is_interactive_idle(worker: WorkerState, tmux: TmuxOrchestrator) -> bool:
    """Detect if an interactive worker has finished its task and is idle.

    Claude Code shows "esc to interrupt" in its status bar while working,
    and removes it when idle. This is the most reliable signal.
    """
    try:
        output = tmux.capture_pane(worker.tmux_window, lines=80)
    except Exception:
        return False

    # Only check the LAST few lines for "esc to interrupt" — the status
    # bar is at the bottom of the pane. Old renders in scrollback may
    # still contain "esc to interrupt" from when the agent was working.
    tail = "\n".join(output.splitlines()[-5:])
    if "esc to interrupt" in tail:
        return False

    # The agent is not actively working. Confirm it actually did work
    # (not just sitting at a fresh prompt that hasn't received input yet).
    # Only agent output markers count — task text alone just means the
    # prompt was sent, not that the agent processed it.
    if "\u23fa" in output or "⎿" in output:
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
