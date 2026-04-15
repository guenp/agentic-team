"""Click CLI entry point for the `team` command."""

from __future__ import annotations

import copy
import os
import shutil
import sys
import warnings
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import click

from . import agents, config, names, status, taskfile
from .models import PROVIDERS
from .tmux import TmuxError, TmuxOrchestrator


PANE_CAPTURE_RETRY_BUDGET = 2


# ── Custom group for bare `team "prompt"` support ────────────────


class TeamGroup(click.Group):
    """A click Group that routes unrecognized subcommands to `send`."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if args and not args[0].startswith("-") and args[0] not in self.commands:
            # Check if it's a typo of a known command before routing to send
            from difflib import get_close_matches
            matches = get_close_matches(args[0], self.commands.keys(), n=1, cutoff=0.6)
            if matches:
                raise click.UsageError(
                    f"Unknown command {args[0]!r}. Did you mean {matches[0]!r}?\n"
                    f"To send a prompt to the lead agent, use: team send {args[0]!r}"
                )
            args = ["send"] + args
        return super().parse_args(ctx, args)

    def invoke(self, ctx: click.Context) -> object:
        try:
            return super().invoke(ctx)
        except (TmuxError, config.StateFileError, taskfile.TaskFileError) as exc:
            raise click.ClickException(str(exc)) from exc


# ── Main group ───────────────────────────────────────────────────


@click.group(cls=TeamGroup)
@click.version_option(version="0.1.0", prog_name="agentic-team")
@click.option(
    "--team", "-T",
    "team_name",
    default=None,
    envvar="TEAM_NAME",
    help="Team to operate on (defaults to the active team).",
)
@click.pass_context
def app(ctx: click.Context, team_name: str | None) -> None:
    """Orchestrate teams of AI coding agents in tmux."""
    ctx.ensure_object(dict)
    ctx.obj["team_name"] = team_name


def _get_team(ctx: click.Context | None = None) -> config.TeamConfig:
    """Get the team config, respecting the --team override."""
    ctx = ctx or click.get_current_context()
    name = ctx.obj.get("team_name") if ctx.obj else None
    if name:
        try:
            return config.load_team(name)
        except FileNotFoundError:
            raise click.ClickException(f"Team {name!r} not found.")
    try:
        return config.get_active_team()
    except RuntimeError:
        raise click.ClickException(
            "No active team. Run 'team init <name>' to create one."
        )


@dataclass
class _PathSnapshot:
    path: Path
    existed: bool
    is_symlink: bool = False
    link_target: str | None = None
    data: bytes | None = None


@dataclass
class _RunAction:
    kind: str
    worker_name: str
    task: str
    workdir: str
    provider: str
    mode: str
    model: str | None = None
    command: str | None = None
    initial_prompt: str | None = None
    existing_window: bool = False


def _snapshot_path(path: Path) -> _PathSnapshot:
    """Capture a file or symlink so transactional commands can roll back."""
    try:
        if path.is_symlink():
            return _PathSnapshot(
                path=path,
                existed=True,
                is_symlink=True,
                link_target=os.readlink(path),
            )
        if path.exists():
            return _PathSnapshot(
                path=path,
                existed=True,
                data=path.read_bytes(),
            )
    except OSError as exc:
        raise config.StateFileError(
            f"Could not snapshot {path} before updating it: {exc}. "
            f"Resolve the filesystem issue and retry."
        ) from exc
    return _PathSnapshot(path=path, existed=False)


def _restore_snapshot(snapshot: _PathSnapshot) -> None:
    """Best-effort rollback for config/state files modified transactionally."""
    path = snapshot.path
    try:
        if path.is_symlink() or path.exists():
            path.unlink()
        if not snapshot.existed:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if snapshot.is_symlink and snapshot.link_target is not None:
            path.symlink_to(snapshot.link_target)
        else:
            path.write_bytes(snapshot.data or b"")
    except OSError as exc:
        warnings.warn(f"Could not restore {path} during rollback: {exc}", stacklevel=2)


def _restore_workers_snapshot(team_name: str, workers: list[config.WorkerState]) -> None:
    """Best-effort rollback for worker state persistence."""
    try:
        config.save_workers(team_name, workers)
    except config.StateFileError as exc:
        warnings.warn(
            f"Could not restore worker state for team {team_name!r}: {exc}",
            stacklevel=2,
        )


def _safe_kill_window(tmux: TmuxOrchestrator, window_name: str) -> None:
    """Best-effort rollback for a worker window created during a failed flow."""
    try:
        tmux.kill_window(window_name)
    except TmuxError as exc:
        warnings.warn(f"Could not rollback tmux window {window_name!r}: {exc}", stacklevel=2)


def _safe_kill_session(tmux: TmuxOrchestrator) -> None:
    """Best-effort rollback for a session created during a failed init."""
    try:
        tmux.kill_session()
    except TmuxError as exc:
        warnings.warn(f"Could not rollback tmux session {tmux.session_name!r}: {exc}", stacklevel=2)


def _safe_remove_tree(path: Path) -> None:
    """Best-effort cleanup for directories created by a failed transaction."""
    try:
        if path.exists():
            shutil.rmtree(path)
    except OSError as exc:
        warnings.warn(f"Could not remove {path} during rollback: {exc}", stacklevel=2)


def _safe_unlink(path: Path) -> None:
    """Best-effort cleanup for a file created during a failed transaction."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        warnings.warn(f"Could not remove {path} during rollback: {exc}", stacklevel=2)


def _mark_worker_running(worker: config.WorkerState, task: str | None = None) -> None:
    """Reset failure state when a worker is dispatched again."""
    if task is not None:
        worker.task = task
    worker.status = "running"
    worker.started_at = datetime.now(timezone.utc).isoformat()
    worker.last_error = None
    worker.exit_code = None


def _capture_pane_text(
    tmux: TmuxOrchestrator,
    target: str,
    *,
    lines: int,
    state_dir: Path | None = None,
    context: str,
) -> str | None:
    """Retry capture-pane a bounded number of times before giving up."""
    last_error: TmuxError | None = None
    for _ in range(PANE_CAPTURE_RETRY_BUDGET):
        try:
            return tmux.capture_pane(target, lines=lines, state_dir=state_dir)
        except TmuxError as exc:
            last_error = exc
    if last_error is not None:
        warnings.warn(
            f"{context} failed after {PANE_CAPTURE_RETRY_BUDGET} attempts: {last_error}",
            stacklevel=2,
        )
    return None


# ── team init ────────────────────────────────────────────────────


@app.command()
@click.argument("name")
@click.option(
    "--provider", "-p",
    default="claude",
    type=click.Choice(sorted(PROVIDERS.keys())),
    help="Team lead agent provider.",
)
@click.option("--model", "-m", default=None, help="Model name (e.g. opus, o4-mini).")
@click.option(
    "--worker-mode",
    default="interactive",
    type=click.Choice(["oneshot", "interactive"]),
    help="Default worker mode.",
)
@click.option(
    "--permissions",
    default="auto",
    type=click.Choice(["auto", "default", "dangerously-skip-permissions"]),
    help="Permission mode for all agents.",
)
@click.option("--max-workers", default=6, help="Max concurrent workers.")
@click.option(
    "--working-dir", "-C",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Working directory for agents.",
)
def init(
    name: str,
    provider: str,
    model: str | None,
    worker_mode: str,
    permissions: str,
    max_workers: int,
    working_dir: str,
) -> None:
    """Initialize a new team and start the team lead agent."""
    team = config.TeamConfig(
        name=name,
        provider=provider,
        model=model,
        worker_mode=worker_mode,
        permissions=permissions,
        max_workers=max_workers,
        working_dir=working_dir,
    )
    tmux = TmuxOrchestrator(team.tmux_session)
    tmux.ensure_available()

    # Check if team already exists with a live session
    if name in config.list_teams():
        existing_tmux = TmuxOrchestrator(team.tmux_session)
        if existing_tmux.session_exists():
            raise click.ClickException(
                f"Team {name!r} is already running. Use 'team stop {name}' first."
            )
        # Stale config, no session — overwrite it
        click.echo(f"Overwriting stale config for {name!r}.")

    team_config_path = config.TEAMS_DIR / f"{name}.toml"
    workers_path = config.STATE_DIR / name / "workers.toml"
    current_log_link = config.LOGS_DIR / name / "current"
    config_snapshot = _snapshot_path(team_config_path)
    workers_snapshot = _snapshot_path(workers_path)
    active_snapshot = _snapshot_path(config.ACTIVE_LINK)
    log_snapshot = _snapshot_path(current_log_link)

    # Create a timestamped session log directory
    session_log_dir = config.create_session_log_dir(name)

    # Write system prompt file and build lead command
    prompt_file = agents.write_system_prompt_file(team)
    lead_cmd = agents.build_lead_command(
        team, prompt_file, log_path=session_log_dir / "lead.log",
    )

    with ExitStack() as rollback:
        rollback.callback(_restore_snapshot, log_snapshot)
        rollback.callback(_restore_snapshot, active_snapshot)
        rollback.callback(_restore_snapshot, workers_snapshot)
        rollback.callback(_restore_snapshot, config_snapshot)
        rollback.callback(_safe_remove_tree, session_log_dir)
        rollback.callback(_safe_unlink, prompt_file)

        # Save config and set as active before any external side effects.
        config.save_team(team)
        config.set_active_team(name)
        config.save_workers(name, [])

        if tmux.session_exists():
            tmux.kill_session()
        rollback.callback(_safe_kill_session, tmux)
        tmux.create_session(working_dir, lead_cmd)
        rollback.pop_all()

    click.echo(f"Team {name!r} initialized.")
    click.echo(f"  Provider: {provider}" + (f" ({model})" if model else ""))
    click.echo(f"  Session:  {team.tmux_session}")
    click.echo(f"  Workdir:  {working_dir}")
    click.echo(f"\nRun 'team attach' to connect, or 'team \"your prompt\"' to send a task.")


# ── team send (also bare `team "prompt"`) ────────────────────────


@app.command()
@click.argument("prompt", nargs=-1, required=True)
def send(prompt: tuple[str, ...]) -> None:
    """Send a prompt to the team lead agent."""
    text = " ".join(prompt)
    team = _get_team()
    tmux = TmuxOrchestrator(team.tmux_session)

    if not tmux.session_exists():
        raise click.ClickException(
            f"tmux session {team.tmux_session!r} not found. Run 'team init' first."
        )

    tmux.send_keys("lead", text)
    click.echo(f"Sent to {team.name} lead.")


# ── team spawn-worker ────────────────────────────────────────────


@app.command("spawn-worker")
@click.option("--task", "-t", required=True, help="Task description for the worker.")
@click.option(
    "--mode",
    default=None,
    type=click.Choice(["oneshot", "interactive"]),
    help="Worker mode (defaults to team setting).",
)
@click.option(
    "--provider",
    default=None,
    type=click.Choice(sorted(PROVIDERS.keys())),
    help="Provider (defaults to team setting).",
)
@click.option("--model", default=None, help="Model override for this worker.")
@click.option("--name", "-n", default=None, help="Custom name for the worker.")
@click.option(
    "--working-dir", "-C",
    default=None,
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Working directory for this worker (defaults to team setting).",
)
@click.option(
    "--resume-session", "-r",
    default=None,
    help="Resume an existing agent session by ID (claude/gemini).",
)
def spawn_worker(
    task: str,
    mode: str | None,
    provider: str | None,
    model: str | None,
    name: str | None,
    working_dir: str | None,
    resume_session: str | None,
) -> None:
    """Spawn a new worker agent."""
    team = _get_team()
    workers = config.load_workers(team.name)
    original_workers = copy.deepcopy(workers)

    # Check limits
    running = [w for w in workers if w.status == "running"]
    if len(running) >= team.max_workers:
        raise click.ClickException(
            f"Max workers ({team.max_workers}) reached. "
            f"Wait for workers to finish or increase --max-workers."
        )

    # Resolve defaults
    mode = mode or team.worker_mode
    provider = provider or team.provider
    model = model or team.model

    # Generate name
    existing_names = [w.name for w in workers]
    worker_name = name or names.name_from_task(task, existing_names)
    if worker_name in existing_names:
        raise click.ClickException(f"Worker name {worker_name!r} is already in use.")

    # Validate resume-session support
    if resume_session:
        from .models import get_provider
        prov_config = get_provider(provider)
        if not prov_config.resume_flag:
            raise click.ClickException(
                f"Provider {provider!r} does not support --resume-session. "
                f"Only claude and gemini support session resume."
            )

    # Build command with log path
    workdir = working_dir or team.working_dir
    if not Path(workdir).is_dir():
        raise click.ClickException(f"Working directory {workdir!r} does not exist.")
    session_log_dir = config.current_session_log_dir(team.name)
    if not session_log_dir:
        session_log_dir = config.create_session_log_dir(team.name)
    log_path = session_log_dir / f"{worker_name}.log"

    if resume_session:
        worker_cmd = agents.build_resume_command(
            provider_name=provider,
            session_id=resume_session,
            prompt=task,
            log_path=log_path,
            mode=mode,
        )
    else:
        worker_cmd = agents.build_worker_command(
            provider_name=provider,
            task=task,
            mode=mode,
            model=model,
            permissions=team.permissions,
            team_name=team.name,
            working_dir=workdir,
            log_path=log_path,
        )

    # Spawn in tmux
    tmux = TmuxOrchestrator(team.tmux_session)
    tmux.ensure_available()
    if not tmux.session_exists():
        raise click.ClickException(
            f"tmux session {team.tmux_session!r} not found. Run 'team init' first."
        )
    state_dir = config.STATE_DIR / team.name
    # For interactive workers, send the task as an initial prompt after the agent starts.
    # For oneshot (including resume), the prompt is baked into the command.
    initial_prompt = task if mode == "interactive" else None

    # Detect if spawned by the lead agent (running inside the team's tmux session)
    source = "lead" if os.environ.get("TMUX", "") else "cli"

    # Record state
    worker = config.WorkerState(
        name=worker_name,
        task=task,
        provider=provider,
        model=model,
        mode=mode,
        tmux_window=worker_name,
        source=source,
        session_id=resume_session,
    )

    with ExitStack() as rollback:
        rollback.callback(_restore_workers_snapshot, team.name, original_workers)
        config.save_workers(team.name, workers + [worker])
        rollback.callback(_safe_kill_window, tmux, worker_name)
        tmux.spawn_worker(
            worker_name,
            worker_cmd,
            workdir,
            state_dir,
            initial_prompt=initial_prompt,
        )
        rollback.pop_all()

    click.echo(f"Spawned worker {worker_name!r} ({mode}) — {task}")


# ── team resume ──────────────────────────────────────────────────


@app.command()
@click.argument("worker_name")
@click.argument("prompt", nargs=-1, required=True)
def resume(worker_name: str, prompt: tuple[str, ...]) -> None:
    """Send a follow-up to a worker (resume oneshot or message interactive)."""
    text = " ".join(prompt)
    team = _get_team()
    tmux = TmuxOrchestrator(team.tmux_session)
    workers = config.load_workers(team.name)
    original_workers = copy.deepcopy(workers)

    tmux.ensure_available()
    if not tmux.session_exists():
        raise click.ClickException(
            f"tmux session {team.tmux_session!r} not found. Run 'team init' first."
        )

    # Find worker (support partial match)
    matched = names.match_name(worker_name, [w.name for w in workers])
    if not matched:
        raise click.ClickException(f"No worker matching {worker_name!r}")
    worker = next(w for w in workers if w.name == matched)

    if worker.mode == "interactive":
        # Interactive agent is still alive — send directly as input
        window_names = {window.name for window in tmux.list_windows()}
        if worker.tmux_window not in window_names:
            raise click.ClickException(
                f"Interactive worker {matched!r} no longer has a live tmux window."
            )
        _mark_worker_running(worker)
        with ExitStack() as rollback:
            rollback.callback(_restore_workers_snapshot, team.name, original_workers)
            config.save_workers(team.name, workers)
            tmux.send_keys(worker.tmux_window, text)
            rollback.pop_all()
        click.echo(f"Sent to {matched}.")
    elif worker.mode == "oneshot" and worker.session_id:
        # Resume via --resume flag
        session_log_dir = config.current_session_log_dir(team.name)
        if not session_log_dir:
            session_log_dir = config.create_session_log_dir(team.name)
        log_path = session_log_dir / f"{matched}.log"
        resume_cmd = agents.build_resume_command(
            worker.provider, worker.session_id, text,
            log_path=log_path,
        )
        state_dir = config.STATE_DIR / team.name
        window_names = {window.name for window in tmux.list_windows()}
        _mark_worker_running(worker)
        with ExitStack() as rollback:
            rollback.callback(_restore_workers_snapshot, team.name, original_workers)
            config.save_workers(team.name, workers)
            if matched in window_names:
                tmux.send_shell_command(matched, resume_cmd, state_dir=state_dir)
            else:
                rollback.callback(_safe_kill_window, tmux, matched)
                tmux.spawn_worker(matched, resume_cmd, team.working_dir, state_dir)
            rollback.pop_all()
        click.echo(f"Resumed {matched} with session {worker.session_id[:8]}...")
    else:
        raise click.ClickException(
            f"Cannot resume {matched}: status={worker.status}, "
            f"mode={worker.mode}, session_id={worker.session_id}"
        )


# ── team status ──────────────────────────────────────────────────


@app.command("status")
@click.argument("worker_name", required=False)
@click.option("--verbose", "-v", is_flag=True, help="Live tail of agent output. Press q to quit.")
def status_cmd(worker_name: str | None, verbose: bool) -> None:
    """Show the status of the active team."""
    team = _get_team()
    st = status.get_team_status(team)

    if not verbose:
        status.format_status(st)
        return

    tmux = TmuxOrchestrator(team.tmux_session)
    state_dir = config.STATE_DIR / team.name
    workers = config.load_workers(team.name)

    # Resolve which workers to show
    if worker_name:
        matched = names.match_name(worker_name, [w.name for w in workers] + ["lead"])
        if not matched:
            raise click.ClickException(f"No worker matching {worker_name!r}")
        targets = [matched]
    else:
        targets = [w.name for w in workers]

    _status_live(team, tmux, state_dir, st, targets)


# ── team wait ──────────────────────────────────────────────────


@app.command()
@click.option("--timeout", "-t", default=600, help="Max seconds to wait (default 600).")
@click.option("--interval", "-i", default=15, help="Seconds between polls (default 15).")
def wait(timeout: int, interval: int) -> None:
    """Block until all running workers are done. Press q to exit early.

    Shows the status table initially, then reprints it only when a
    worker's status changes. Uses one tool call in the lead's context
    instead of repeated status checks.
    """
    import select
    import sys
    import termios
    import time
    import tty

    team = _get_team()
    start = time.time()

    # Track status per worker to detect changes
    prev_statuses: dict[str, str] = {}

    # Set up non-blocking key reads if stdin is a terminal
    is_tty = sys.stdin.isatty()
    old_settings = None
    if is_tty:
        old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())

    try:
        while True:
            st = status.get_team_status(team)
            workers = st["workers"]
            active = [w for w in workers if w["status"] in ("running", "waiting")]
            waiting = [w for w in workers if w["status"] == "waiting"]
            cur_statuses = {w["name"]: w["status"] for w in workers}

            # Print table on first poll or when any worker's status changed
            if cur_statuses != prev_statuses:
                elapsed = int(time.time() - start)
                click.echo(f"\n--- {elapsed}s elapsed ---")
                status.format_status(st)
                if waiting:
                    names = ", ".join(w["name"] for w in waiting)
                    click.echo(f"⚠ {len(waiting)} worker(s) waiting for input: {names}")
                click.secho("press q to quit", dim=True)
                prev_statuses = cur_statuses

            if not active:
                break

            elapsed = int(time.time() - start)
            if elapsed >= timeout:
                click.echo(f"\nTimed out after {timeout}s. {len(active)} worker(s) still active.")
                return

            # Sleep in small increments, checking for 'q' keypress
            deadline = time.time() + interval
            while time.time() < deadline:
                if is_tty and select.select([sys.stdin], [], [], 0.5)[0]:
                    ch = sys.stdin.read(1)
                    if ch in ("q", "Q"):
                        elapsed = int(time.time() - start)
                        click.echo(f"\nExited after {elapsed}s. {len(active)} worker(s) still active.")
                        return
                else:
                    time.sleep(0.5)

        elapsed = int(time.time() - start)
        done = [w for w in workers if w["status"] == "done"]
        errors = [w for w in workers if w["status"] == "error"]
        if errors:
            click.echo(
                f"\nAll workers reached a terminal state in {elapsed}s: "
                f"{len(done)} done, {len(errors)} error."
            )
        else:
            click.echo(f"\nAll {len(done)} worker(s) done in {elapsed}s.")
    finally:
        if old_settings is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


# ── team standup ────────────────────────────────────────────────


STANDUP_PROMPT = """\
Check on all workers and write a standup report. Do these steps:

1. Run `team status` to see current worker states.
2. Run `team logs <name>` for each worker to review their output.
3. Write a standup report to the file path below.

Report file: {report_path}

Use EXACTLY this format (markdown):

```
# Standup — {team_name}

## <worker-name> — done | running | error
**Task:** <one-line task description>
**Result:** <1-2 sentences: what was accomplished, key findings, or what failed>
**Output:** <where to find the full result — a PR URL, file path, or `team logs <name>`>
```

Include a section for every worker. Be concise — this is a status summary, \
not a full report. Write the file, then say "Standup written."\
"""


@app.command()
@click.option("--timeout", default=120, help="Max seconds to wait for the report.")
@click.option("--verbose", "-v", is_flag=True, help="Stream the lead agent's output live.")
def standup(timeout: int, verbose: bool) -> None:
    """Ask the team lead for a standup report on all workers."""
    team = _get_team()
    tmux = TmuxOrchestrator(team.tmux_session)

    if not tmux.session_exists():
        raise click.ClickException(
            f"tmux session {team.tmux_session!r} not found. Run 'team init' first."
        )

    state_dir = config.STATE_DIR / team.name
    report_path = state_dir / "standup.md"
    report_path.unlink(missing_ok=True)

    prompt = STANDUP_PROMPT.format(
        report_path=report_path,
        team_name=team.name,
    )
    tmux.send_keys("lead", prompt)

    import time

    if verbose:
        _standup_live(team, tmux, report_path, timeout)
    else:
        click.echo("Asking lead for standup report...")
        _standup_poll(team, tmux, report_path, timeout)


def _standup_done(report_path: Path) -> bool:
    """Check if the standup report file has been written."""
    return report_path.exists() and report_path.stat().st_size > 0


def _lead_is_idle(tmux: TmuxOrchestrator, provider: str) -> bool:
    """Check if the lead agent is idle (not actively processing)."""
    raw = _capture_pane_text(
        tmux,
        "lead",
        lines=30,
        context="checking lead idleness",
    )
    if raw is None:
        return False
    raw = raw.rstrip()
    tail = "\n".join(raw.splitlines()[-10:])
    if provider == "claude":
        return "esc to inter" not in tail and len(
            [l for l in raw.splitlines() if l.strip()]
        ) > 5
    return False


def _standup_poll(
    team: config.TeamConfig,
    tmux: TmuxOrchestrator,
    report_path: Path,
    timeout: int,
) -> None:
    """Wait for the standup report by polling (default mode)."""
    import time

    start = time.time()
    idle_count = 0

    while time.time() - start < timeout:
        time.sleep(3)

        if _standup_done(report_path):
            time.sleep(1)
            break

        if _lead_is_idle(tmux, team.provider):
            idle_count += 1
            if idle_count >= 2:
                break
        else:
            idle_count = 0

        elapsed = int(time.time() - start)
        if elapsed % 15 == 0 and elapsed > 0:
            click.echo(f"  still waiting... ({elapsed}s)")

    _show_standup_result(tmux, report_path)


def _standup_live(
    team: config.TeamConfig,
    tmux: TmuxOrchestrator,
    report_path: Path,
    timeout: int,
) -> None:
    """Stream the lead agent's pane output live while waiting."""
    import time

    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel

    console = Console()
    start = time.time()
    idle_count = 0

    with Live(console=console, refresh_per_second=2, transient=True) as live:
        while time.time() - start < timeout:
            display = _pane_tail(tmux, "lead", n=5)

            elapsed = int(time.time() - start)
            live.update(Panel(
                display,
                title=f"[bold]Lead Agent[/bold] [dim]({elapsed}s)[/dim]",
                border_style="blue",
            ))

            if _standup_done(report_path):
                time.sleep(1)
                break

            if _lead_is_idle(tmux, team.provider):
                idle_count += 1
                if idle_count >= 2:
                    break
            else:
                idle_count = 0

            time.sleep(0.5)

    _show_standup_result(tmux, report_path)


def _show_standup_result(tmux: TmuxOrchestrator, report_path: Path) -> None:
    """Display the standup report or fall back to pane capture."""
    if _standup_done(report_path):
        _render_markdown(report_path.read_text())
    else:
        click.echo()
        click.echo("(Lead didn't write the report file — showing pane output)")
        click.echo()
        output = _capture_pane_text(
            tmux,
            "lead",
            lines=80,
            context="capturing standup output",
        )
        if output is not None:
            output = output.rstrip()
            for line in output.splitlines():
                if line.strip():
                    click.echo(line)
        else:
            click.echo("Could not capture lead pane.")


# ── Shared helpers for live pane display ─────────────────────────


def _pane_tail(
    tmux: TmuxOrchestrator,
    target: str,
    n: int = 5,
    state_dir: Path | None = None,
) -> str:
    """Capture the last *n* meaningful lines from a pane.

    Strips blank lines and separator-only lines (───).
    """
    raw = _capture_pane_text(
        tmux,
        target,
        lines=30,
        state_dir=state_dir,
        context=f"capturing pane tail for {target}",
    )
    if raw is None:
        return "(pane not available)"
    raw = raw.rstrip()
    lines = [
        l.rstrip() for l in raw.splitlines()
        if l.strip()
        and not all(c in "─▀▄━═" for c in l.strip())
    ]
    return "\n".join(lines[-n:]) if lines else "(no output)"


def _status_live(
    team: config.TeamConfig,
    tmux: TmuxOrchestrator,
    state_dir: Path,
    st: dict,
    targets: list[str],
) -> None:
    """Live-updating status with tailed pane output. Press q to quit."""
    import select
    import sys
    import termios
    import time
    import tty

    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text

    console = Console()
    status_colors = {"running": "yellow", "done": "green", "error": "red"}

    is_tty = sys.stdin.isatty()

    def _render_panels() -> Group:
        st = status.get_team_status(team)
        worker_map = {w["name"]: w for w in st["workers"]}

        panels = []
        for name in targets:
            w = worker_map.get(name, {})
            ws = w.get("status", "?")
            elapsed = w.get("elapsed", "")
            task = w.get("task", "")
            if len(task) > 60:
                task = task[:57] + "..."
            color = status_colors.get(ws, "white")

            tail = _pane_tail(tmux, name, n=5, state_dir=state_dir)

            header = Text()
            header.append(f"  {ws}", style=f"bold {color}")
            header.append(f"  {elapsed}", style="dim")
            header.append(f"  {task}", style="dim")

            panels.append(Panel(
                tail,
                title=f"[bold cyan]{name}[/bold cyan]",
                subtitle=header,
                border_style=color,
            ))
        return Group(*panels)

    # No tty: print a single snapshot and exit
    if not is_tty:
        console.print(_render_panels())
        return

    # Interactive: live-updating display with 'q' to quit
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        tty.setcbreak(fd)

        with Live(console=console, refresh_per_second=2) as live:
            while True:
                if select.select([sys.stdin], [], [], 0)[0]:
                    ch = sys.stdin.read(1)
                    if ch in ("q", "Q"):
                        break

                live.update(Group(_render_panels(), Text("press q to quit", style="dim")))
                time.sleep(0.5)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _render_markdown(text: str) -> None:
    """Render markdown to the terminal using rich."""
    from rich.console import Console
    from rich.markdown import Markdown

    console = Console()
    console.print()
    console.print(Markdown(text))
    console.print()


# ── team attach ──────────────────────────────────────────────────


@app.command()
@click.option("--window", "-w", default=None, help="Window name to select.")
@click.option("--multi", "-m", is_flag=True, help="Tiled dashboard showing all workers.")
def attach(window: str | None, multi: bool) -> None:
    """Attach to the team's tmux session."""
    team = _get_team()
    tmux = TmuxOrchestrator(team.tmux_session)

    if not tmux.session_exists():
        raise click.ClickException(
            f"tmux session {team.tmux_session!r} not found."
        )

    state_dir = config.STATE_DIR / team.name

    if multi:
        # Include all workers that still have a live tmux window
        windows = {w.name for w in tmux.list_windows()}
        workers = config.load_workers(team.name)
        targets = [w.name for w in workers if w.tmux_window in windows]
        if not targets:
            raise click.ClickException("No workers to display.")
        tmux.multi_attach(targets, state_dir)
    else:
        # Undo multi layout if active, restoring individual tabs
        tmux.break_multi(state_dir)
        # Support partial name matching for window
        if window:
            workers = config.load_workers(team.name)
            matched = names.match_name(window, [w.name for w in workers] + ["lead"])
            window = matched or window
        tmux.attach(window)


# ── team logs ────────────────────────────────────────────────────


@app.command()
@click.argument("worker_name", required=False)
@click.option("--tail", "-n", default=50, help="Number of lines to show.")
@click.option("--all", "-a", "show_all", is_flag=True, help="Show logs for all workers.")
def logs(worker_name: str | None, tail: int, show_all: bool) -> None:
    """View worker logs from the current session.

    Logs are written by each agent CLI's built-in logging (--verbose,
    RUST_LOG, --debug) to a timestamped session directory.

    With no arguments or --all, shows logs for every worker.
    With a name, shows logs for that specific worker.
    """
    team = _get_team()
    workers = config.load_workers(team.name)

    if worker_name and not show_all:
        targets = [worker_name]
    elif show_all or not worker_name:
        targets = [w.name for w in workers]
        if not targets:
            click.echo("No workers.")
            return
    else:
        targets = [worker_name]

    # Resolve names (partial match, also allow "lead")
    all_names = [w.name for w in workers] + ["lead"]
    resolved = []
    for t in targets:
        matched = names.match_name(t, all_names) or t
        resolved.append(matched)

    session_log_dir = config.current_session_log_dir(team.name)
    tmux = TmuxOrchestrator(team.tmux_session)
    state_dir = config.STATE_DIR / team.name

    for i, matched in enumerate(resolved):
        w = next((w for w in workers if w.name == matched), None)
        st = w.status if w else "?"
        task = w.task if w else ""
        if len(task) > 60:
            task = task[:57] + "..."
        status_color = {"running": "yellow", "done": "green", "error": "red"}.get(st, "white")
        click.echo()
        click.echo(click.style(f"{'━' * 60}", fg="bright_black"))
        click.echo(
            click.style(f"  {matched}", fg="cyan", bold=True)
            + click.style(f"  {st}", fg=status_color)
            + click.style(f"  {task}", fg="bright_black")
        )
        click.echo(click.style(f"{'━' * 60}", fg="bright_black"))

        # Try log file first; fall back to capture-pane for interactive
        # TUI agents (Claude, Codex) that don't write to stderr.
        log_path = session_log_dir / f"{matched}.log" if session_log_dir else None
        has_log = log_path and log_path.exists() and log_path.stat().st_size > 0
        if has_log:
            lines = log_path.read_text().splitlines()
            for line in lines[-tail:]:
                click.echo(line)
        elif tmux.session_exists():
            output = _capture_pane_text(
                tmux,
                matched,
                lines=tail,
                state_dir=state_dir,
                context=f"capturing logs for {matched}",
            )
            if output is not None:
                pane_lines = [l for l in output.splitlines() if l.strip()]
                if pane_lines:
                    for line in pane_lines[-tail:]:
                        click.echo(line)
                else:
                    click.echo("  (no output yet)")
            else:
                click.echo("  (pane not available)")
        else:
            click.echo("  (no log file)")

        if i < len(resolved) - 1:
            click.echo()


# ── team send-to-worker ─────────────────────────────────────────


@app.command("send-to-worker")
@click.argument("worker_name")
@click.argument("message", nargs=-1, required=True)
def send_to_worker(worker_name: str, message: tuple[str, ...]) -> None:
    """Send a message to a running interactive worker."""
    text = " ".join(message)
    team = _get_team()
    tmux = TmuxOrchestrator(team.tmux_session)
    workers = config.load_workers(team.name)

    matched = names.match_name(worker_name, [w.name for w in workers])
    if not matched:
        raise click.ClickException(f"No worker matching {worker_name!r}")

    state_dir = config.STATE_DIR / team.name
    tmux.send_keys(matched, text, state_dir=state_dir)
    click.echo(f"Sent to {matched}.")


# ── team stop-worker ─────────────────────────────────────────────


@app.command("stop-worker")
@click.argument("worker_name")
def stop_worker(worker_name: str) -> None:
    """Stop a specific worker."""
    team = _get_team()
    tmux = TmuxOrchestrator(team.tmux_session)
    workers = config.load_workers(team.name)

    matched = names.match_name(worker_name, [w.name for w in workers])
    if not matched:
        raise click.ClickException(f"No worker matching {worker_name!r}")

    tmux.kill_window(matched)

    for w in workers:
        if w.name == matched:
            w.status = "done"
    config.save_workers(team.name, workers)
    click.echo(f"Stopped {matched}.")


# ── team run ─────────────────────────────────────────────────────


@app.command()
@click.argument("task_file", type=click.Path(exists=True, dir_okay=False, resolve_path=True))
@click.option("--limit", "-l", default=None, type=int, help="Max tasks to spawn (defaults to team max_workers).")
@click.option("--dry-run", is_flag=True, help="Show what would be spawned without doing it.")
@click.option("--rerun", is_flag=True, help="Re-run completed tasks by resuming existing workers.")
def run(task_file: str, limit: int | None, dry_run: bool, rerun: bool) -> None:
    """Spawn workers for unchecked tasks in a markdown file.

    The file uses checkbox syntax grouped by headings:

    \b
        ## ~/repos/backend
        - [ ] Fix the login bug
        - [ ] Add tests (provider: codex, mode: interactive)
        ## ~/repos/frontend
        - [ ] Update the landing page

    Headings set the working directory. Inline (key: value) overrides
    provider, mode, model, or name per task. Re-run to pick up remaining
    unchecked tasks.
    """
    team = _get_team()
    path = Path(task_file)

    # Sync status first so we have up-to-date worker states
    st = status.get_team_status(team)
    worker_status_map = {w["name"]: w["status"] for w in st["workers"]}

    # Separate tasks into: new (no worker), rerunnable (done worker), running (skip)
    all_pending = taskfile.pending_tasks(path)
    workers = config.load_workers(team.name)
    worker_by_name = {w.name: w for w in workers}

    # Match tasks to existing workers by task text
    worker_by_task = {w.task: w for w in workers}

    new_tasks: list[taskfile.TaskEntry] = []
    rerun_tasks: list[taskfile.TaskEntry] = []
    running_skip = 0

    for entry in all_pending:
        # Try annotation first, then match by task text
        matched_worker = None
        if entry.worker_name and entry.worker_name in worker_by_name:
            matched_worker = worker_by_name[entry.worker_name]
        elif entry.task in worker_by_task:
            matched_worker = worker_by_task[entry.task]
            entry.worker_name = matched_worker.name

        if matched_worker and matched_worker.name in worker_status_map:
            ws = worker_status_map[matched_worker.name]
            if ws == "running":
                running_skip += 1
                continue
            if ws == "done":
                if rerun:
                    rerun_tasks.append(entry)
                else:
                    running_skip += 1
                continue
        new_tasks.append(entry)

    actionable = rerun_tasks + new_tasks if rerun else new_tasks

    if not actionable:
        if running_skip:
            msg = f"All tasks already handled ({running_skip} done/running)."
            if not rerun:
                msg += " Use --rerun to re-run completed tasks."
            click.echo(msg)
        else:
            click.echo("No pending tasks found.")
        return

    running_count = len([w for w in workers if w.status == "running"])
    slots = (limit or team.max_workers) - running_count

    if slots <= 0:
        raise click.ClickException(
            f"No worker slots available ({running_count} running, max {team.max_workers}). "
            f"Wait for workers to finish or use --limit."
        )

    to_act = actionable[:slots]

    planned_workers = copy.deepcopy(workers)
    planned_by_name = {w.name: w for w in planned_workers}
    reserved_names = set(planned_by_name)

    plan_specs: list[tuple[str, taskfile.TaskEntry, config.WorkerState | None, str, str, str | None, str, str]] = []
    for entry in to_act:
        prov = entry.provider or team.provider
        if prov not in PROVIDERS:
            raise click.ClickException(f"Unknown provider {prov!r} in {path}.")
        mode = entry.mode or team.worker_mode
        if mode not in {"oneshot", "interactive"}:
            raise click.ClickException(f"Unsupported worker mode {mode!r} in {path}.")
        model = entry.model or team.model
        workdir = entry.working_dir or team.working_dir
        if not Path(workdir).is_dir():
            raise click.ClickException(
                f"Task {entry.task!r} references missing working directory {workdir!r}."
            )

        existing_worker = planned_by_name.get(entry.worker_name) if entry.worker_name else None
        if existing_worker and existing_worker.status == "done":
            _mark_worker_running(existing_worker, task=entry.task)
            plan_specs.append(("rerun", entry, existing_worker, existing_worker.name, prov, model, mode, workdir))
            continue

        worker_name = entry.name or names.name_from_task(entry.task, list(reserved_names))
        if worker_name in reserved_names:
            raise click.ClickException(
                f"Task {entry.task!r} wants worker name {worker_name!r}, but that name is already in use."
            )

        new_worker = config.WorkerState(
            name=worker_name,
            task=entry.task,
            provider=prov,
            model=model,
            mode=mode,
            tmux_window=worker_name,
            source="file",
        )
        planned_workers.append(new_worker)
        planned_by_name[worker_name] = new_worker
        reserved_names.add(worker_name)
        plan_specs.append(("spawn", entry, new_worker, worker_name, prov, model, mode, workdir))

    if dry_run:
        for kind, entry, existing_worker, worker_name, prov, _, mode, workdir in plan_specs:
            tag = " (rerun)" if kind == "rerun" else ""
            click.echo(f"  - {entry.task}{tag}")
            click.echo(f"    worker={worker_name}  dir={workdir}  provider={prov}  mode={mode}")
        return

    tmux = TmuxOrchestrator(team.tmux_session)
    tmux.ensure_available()
    if not tmux.session_exists():
        raise click.ClickException(
            f"tmux session {team.tmux_session!r} not found. Run 'team init' first."
        )

    live_windows = {window.name for window in tmux.list_windows()}
    session_log_dir = config.current_session_log_dir(team.name)
    if not session_log_dir:
        session_log_dir = config.create_session_log_dir(team.name)

    actions: list[_RunAction] = []
    for kind, entry, existing_worker, worker_name, prov, model, mode, workdir in plan_specs:
        log_path = session_log_dir / f"{worker_name}.log"
        if kind == "rerun" and existing_worker is not None:
            if existing_worker.mode == "interactive":
                if existing_worker.tmux_window not in live_windows:
                    raise click.ClickException(
                        f"Interactive worker {worker_name!r} no longer has a live tmux window."
                    )
                actions.append(_RunAction(
                    kind="rerun-interactive",
                    worker_name=worker_name,
                    task=entry.task,
                    workdir=workdir,
                    provider=existing_worker.provider,
                    mode=existing_worker.mode,
                    model=existing_worker.model,
                    existing_window=True,
                ))
                continue

            if existing_worker.session_id and existing_worker.provider == "claude":
                command = agents.build_resume_command(
                    existing_worker.provider,
                    existing_worker.session_id,
                    entry.task,
                    log_path=log_path,
                )
                actions.append(_RunAction(
                    kind="rerun-shell",
                    worker_name=worker_name,
                    task=entry.task,
                    workdir=workdir,
                    provider=existing_worker.provider,
                    mode=existing_worker.mode,
                    model=existing_worker.model,
                    command=command,
                    existing_window=worker_name in live_windows,
                ))
                continue

            command = agents.build_worker_command(
                provider_name=existing_worker.provider,
                task=entry.task,
                mode=existing_worker.mode,
                model=existing_worker.model or model,
                permissions=team.permissions,
                team_name=team.name,
                working_dir=workdir,
                log_path=log_path,
            )
            actions.append(_RunAction(
                kind="rerun-shell",
                worker_name=worker_name,
                task=entry.task,
                workdir=workdir,
                provider=existing_worker.provider,
                mode=existing_worker.mode,
                model=existing_worker.model or model,
                command=command,
                existing_window=worker_name in live_windows,
            ))
            continue

        command = agents.build_worker_command(
            provider_name=prov,
            task=entry.task,
            mode=mode,
            model=model,
            permissions=team.permissions,
            team_name=team.name,
            working_dir=workdir,
            log_path=log_path,
        )
        actions.append(_RunAction(
            kind="spawn",
            worker_name=worker_name,
            task=entry.task,
            workdir=workdir,
            provider=prov,
            mode=mode,
            model=model,
            command=command,
            initial_prompt=entry.task if mode == "interactive" else None,
        ))

    original_workers = copy.deepcopy(workers)
    state_dir = config.STATE_DIR / team.name
    spawned = 0
    resumed = 0

    with ExitStack() as rollback:
        rollback.callback(_restore_workers_snapshot, team.name, original_workers)
        config.save_workers(team.name, planned_workers)

        for action in actions:
            if action.kind == "spawn" and action.command is not None:
                rollback.callback(_safe_kill_window, tmux, action.worker_name)
                tmux.spawn_worker(
                    action.worker_name,
                    action.command,
                    action.workdir,
                    state_dir,
                    initial_prompt=action.initial_prompt,
                )
                spawned += 1
                click.echo(f"  {action.worker_name} | {action.task}")
                continue

            if action.kind == "rerun-interactive":
                tmux.send_keys(action.worker_name, action.task)
                resumed += 1
                click.echo(f"  {action.worker_name} | {action.task} (rerun)")
                continue

            if action.kind == "rerun-shell" and action.command is not None:
                if action.existing_window:
                    tmux.send_shell_command(action.worker_name, action.command, state_dir=state_dir)
                else:
                    rollback.callback(_safe_kill_window, tmux, action.worker_name)
                    tmux.spawn_worker(action.worker_name, action.command, action.workdir, state_dir)
                resumed += 1
                click.echo(f"  {action.worker_name} | {action.task} (rerun)")
                continue

        rollback.pop_all()

    # Try to deliver pending prompts (agents may need a moment to start)
    import time
    if spawned:
        click.echo("\nWaiting for agents to start...")
        for _ in range(10):
            time.sleep(1)
            run_state_dir = config.STATE_DIR / team.name
            delivered = tmux.deliver_pending_prompts(run_state_dir)
            if delivered:
                click.echo(f"  Delivered prompts to: {', '.join(delivered)}")
            # Check if all pending prompts are delivered
            pending_dir = run_state_dir / "pending_prompts"
            if not pending_dir.exists() or not list(pending_dir.iterdir()):
                break

    parts = []
    if spawned:
        parts.append(f"{spawned} spawned")
    if resumed:
        parts.append(f"{resumed} rerun")
    click.echo(f"\n{', '.join(parts)}. Run 'team status' to monitor.")


# ── team sync (update task file from worker status) ──────────────


@app.command()
@click.argument("task_file", type=click.Path(exists=True, dir_okay=False, resolve_path=True))
def sync(task_file: str) -> None:
    """Update a task file's checkboxes from current worker status.

    Ticks off completed tasks and updates the status annotations.
    """
    team = _get_team()
    path = Path(task_file)
    all_tasks = taskfile.parse_task_file(path)
    st = status.get_team_status(team)
    worker_map = {w["name"]: w for w in st["workers"]}

    updates: dict[int, taskfile.TaskEntry] = {}

    for entry in all_tasks:
        if entry.done and not entry.worker_name:
            continue  # Already done before we touched it

        # Match task to worker by checking annotations in the file
        # Re-parse the line to find the worker name from the ← annotation
        lines = path.read_text().splitlines()
        if entry.line_number < len(lines):
            line = lines[entry.line_number]
            import re
            arrow_match = re.search(r"←\s*(\S+)", line)
            if arrow_match:
                wname = arrow_match.group(1)
                if wname in worker_map:
                    w = worker_map[wname]
                    entry.worker_name = wname
                    entry.worker_status = w["status"]
                    entry.elapsed = w["elapsed"]
                    if w["status"] == "done":
                        entry.done = True
                    updates[entry.line_number] = entry

    if not updates:
        click.echo("No updates to sync.")
        return

    taskfile.update_task_file(path, updates)
    done_count = sum(1 for e in updates.values() if e.done)
    click.echo(f"Synced {len(updates)} tasks ({done_count} completed).")


# ── team clear ───────────────────────────────────────────────────


@app.command()
def clear() -> None:
    """Remove completed workers and close their tmux windows.

    Also cleans up orphaned tmux windows that are no longer tracked
    in the workers list (e.g. from a previous clear that didn't kill
    the windows).
    """
    team = _get_team()
    tmux = TmuxOrchestrator(team.tmux_session)
    workers = config.load_workers(team.name)

    # Kill tmux windows for done workers
    done = [w for w in workers if w.status == "done"]
    for w in done:
        tmux.kill_window(w.tmux_window)

    remaining = [w for w in workers if w.status != "done"]
    running_names = {w.tmux_window for w in remaining} | {"lead"}

    # Kill orphaned tmux windows not tracked in workers list
    orphaned = 0
    for win in tmux.list_windows():
        if win.name not in running_names:
            tmux.kill_window(win.name)
            orphaned += 1

    if not done and not orphaned:
        click.echo("Nothing to clear.")
        return

    config.save_workers(team.name, remaining)
    parts = []
    if done:
        parts.append(f"{len(done)} completed worker(s)")
    if orphaned:
        parts.append(f"{orphaned} orphaned window(s)")
    click.echo(f"Cleared {', '.join(parts)}. {len(remaining)} remaining.")


# ── team stop ────────────────────────────────────────────────────


@app.command()
@click.argument("name", required=False)
def stop(name: str | None) -> None:
    """Stop a team and kill its tmux session.

    If NAME is given, stops that team. Otherwise stops the active team.
    """
    if name:
        try:
            team = config.load_team(name)
        except FileNotFoundError:
            raise click.ClickException(f"Team {name!r} not found.")
    else:
        team = _get_team()

    tmux = TmuxOrchestrator(team.tmux_session)
    tmux.kill_session()

    # Clear active link if this was the active team
    if config.get_active_team_name() == team.name:
        config.clear_active_team()

    click.echo(f"Team {team.name!r} stopped.")


# ── team list ────────────────────────────────────────────────────


@app.command("list")
def list_cmd() -> None:
    """List all teams."""
    team_names = config.list_teams()
    if not team_names:
        click.echo("No teams. Run 'team init <name>' to create one.")
        return

    active = config.get_active_team_name()
    for name in team_names:
        marker = " (active)" if name == active else ""
        team = config.load_team(name)
        tmux = TmuxOrchestrator(team.tmux_session)
        alive = "running" if tmux.session_exists() else "stopped"
        click.echo(f"  {name}{marker} — {team.provider} — {alive}")
