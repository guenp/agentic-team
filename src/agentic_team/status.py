"""Status polling and formatting for team workers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .config import (
    STATE_DIR,
    TeamConfig,
    WorkerState,
    load_workers,
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
        # Re-evaluate interactive workers previously marked "done" —
        # their pane persists and they may be working on a new task.
        if worker.mode == "interactive" and worker.status == "done":
            in_windows = (
                worker.tmux_window in windows
                or worker.tmux_window in multi_joined
            )
            if in_windows and not tmux.is_pane_dead(worker.tmux_window, state_dir=state_dir):
                if not _is_interactive_idle(worker, tmux, state_dir):
                    worker.status = "running"
                    updated = True
            continue

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
        # Skip if the worker's initial prompt hasn't been delivered yet.
        if (
            worker.mode == "interactive"
            and worker.name not in pending_workers
            and _is_interactive_idle(worker, tmux, state_dir)
        ):
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
            "source": getattr(w, "source", "cli"),
            "elapsed": elapsed,
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

    status_styles = {
        "running": "bold yellow",
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
        table.add_row(
            w["name"],
            w["provider"],
            Text(w["status"], style=style),
            w["elapsed"],
            task_col,
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
        raw = tmux.capture_pane(
            worker.tmux_window, lines=30, state_dir=state_dir,
        )
    except Exception:
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
