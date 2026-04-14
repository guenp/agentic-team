"""Click CLI entry point for the `team` command."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from . import agents, config, names, status, taskfile
from .models import PROVIDERS
from .tmux import TmuxOrchestrator


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


# ── Main group ───────────────────────────────────────────────────


@click.group(cls=TeamGroup)
@click.version_option(version="0.1.0", prog_name="agentic-team")
def app() -> None:
    """Orchestrate teams of AI coding agents in tmux."""


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
    # Check if team already exists with a live session
    if name in config.list_teams():
        existing_tmux = TmuxOrchestrator(f"team-{name}")
        if existing_tmux.session_exists():
            raise click.ClickException(
                f"Team {name!r} is already running. Use 'team stop {name}' first."
            )
        # Stale config, no session — overwrite it
        click.echo(f"Overwriting stale config for {name!r}.")

    team = config.TeamConfig(
        name=name,
        provider=provider,
        model=model,
        worker_mode=worker_mode,
        permissions=permissions,
        max_workers=max_workers,
        working_dir=working_dir,
    )

    # Save config and set as active
    config.save_team(team)
    config.set_active_team(name)
    config.save_workers(name, [])

    # Write system prompt file and build lead command
    prompt_file = agents.write_system_prompt_file(team)
    lead_cmd = agents.build_lead_command(team, prompt_file)

    # Create tmux session and start the lead
    tmux = TmuxOrchestrator(team.tmux_session)
    if tmux.session_exists():
        tmux.kill_session()
    tmux.create_session(working_dir, lead_cmd)

    # Start logging the lead
    log_dir = config.log_dir_for_team(name)
    tmux.start_logging("lead", log_dir / "lead.log")

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
    team = config.get_active_team()
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
def spawn_worker(
    task: str,
    mode: str | None,
    provider: str | None,
    model: str | None,
    name: str | None,
    working_dir: str | None,
) -> None:
    """Spawn a new worker agent."""
    team = config.get_active_team()
    workers = config.load_workers(team.name)

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
    worker_name = name or names.next_name(existing_names)

    # Build command
    worker_cmd = agents.build_worker_command(
        provider_name=provider,
        task=task,
        mode=mode,
        model=model,
        permissions=team.permissions,
    )

    # Spawn in tmux
    tmux = TmuxOrchestrator(team.tmux_session)
    log_path = config.log_dir_for_team(team.name) / f"{worker_name}.log"
    workdir = working_dir or team.working_dir
    # For interactive workers, send the task as an initial prompt after the agent starts
    initial_prompt = task if mode == "interactive" else None
    tmux.spawn_worker(worker_name, worker_cmd, workdir, log_path, initial_prompt=initial_prompt)

    # Record state
    worker = config.WorkerState(
        name=worker_name,
        task=task,
        provider=provider,
        model=model,
        mode=mode,
        tmux_window=worker_name,
    )
    workers.append(worker)
    config.save_workers(team.name, workers)

    click.echo(f"Spawned worker {worker_name!r} ({mode}) — {task}")


# ── team resume ──────────────────────────────────────────────────


@app.command()
@click.argument("worker_name")
@click.argument("prompt", nargs=-1, required=True)
def resume(worker_name: str, prompt: tuple[str, ...]) -> None:
    """Send a follow-up to a worker (resume oneshot or message interactive)."""
    text = " ".join(prompt)
    team = config.get_active_team()
    tmux = TmuxOrchestrator(team.tmux_session)
    workers = config.load_workers(team.name)

    # Find worker (support partial match)
    matched = names.match_name(worker_name, [w.name for w in workers])
    if not matched:
        raise click.ClickException(f"No worker matching {worker_name!r}")
    worker = next(w for w in workers if w.name == matched)

    if worker.mode == "interactive":
        # Interactive agent is still alive — send directly as input
        tmux.send_keys(worker.tmux_window, text)
        worker.status = "running"
        config.save_workers(team.name, workers)
        click.echo(f"Sent to {matched}.")
    elif worker.mode == "oneshot" and worker.session_id:
        # Resume via --resume flag
        resume_cmd = agents.build_resume_command(
            worker.provider, worker.session_id, text
        )
        log_path = config.log_dir_for_team(team.name) / f"{matched}.log"
        tmux.spawn_worker(matched, resume_cmd, team.working_dir, log_path)
        worker.status = "running"
        config.save_workers(team.name, workers)
        click.echo(f"Resumed {matched} with session {worker.session_id[:8]}...")
    else:
        raise click.ClickException(
            f"Cannot resume {matched}: status={worker.status}, "
            f"mode={worker.mode}, session_id={worker.session_id}"
        )


# ── team status ──────────────────────────────────────────────────


@app.command("status")
def status_cmd() -> None:
    """Show the status of the active team."""
    team = config.get_active_team()
    st = status.get_team_status(team)
    click.echo(status.format_status(st))


# ── team attach ──────────────────────────────────────────────────


@app.command()
@click.option("--window", "-w", default=None, help="Window name to select.")
def attach(window: str | None) -> None:
    """Attach to the team's tmux session."""
    team = config.get_active_team()
    tmux = TmuxOrchestrator(team.tmux_session)

    if not tmux.session_exists():
        raise click.ClickException(
            f"tmux session {team.tmux_session!r} not found."
        )

    # Support partial name matching for window
    if window:
        workers = config.load_workers(team.name)
        matched = names.match_name(window, [w.name for w in workers] + ["lead"])
        window = matched or window

    tmux.attach(window)


# ── team logs ────────────────────────────────────────────────────


@app.command()
@click.argument("worker_name", required=False)
@click.option("--tail", "-n", default=50, help="Number of lines to capture from the pane.")
@click.option("--raw", is_flag=True, help="Read raw pipe-pane log file instead of capture-pane.")
@click.option("--all", "-a", "show_all", is_flag=True, help="Show logs for all workers.")
def logs(worker_name: str | None, tail: int, raw: bool, show_all: bool) -> None:
    """View worker output via tmux capture-pane.

    With no arguments or --all, shows logs for every worker.
    With a name, shows logs for that specific worker.
    """
    team = config.get_active_team()
    tmux = TmuxOrchestrator(team.tmux_session)
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

    if not tmux.session_exists() and not raw:
        raise click.ClickException(f"tmux session {team.tmux_session!r} not found.")

    for i, matched in enumerate(resolved):
        if len(resolved) > 1:
            # Find worker status for the header
            w = next((w for w in workers if w.name == matched), None)
            st = w.status if w else "?"
            task = w.task if w else ""
            if len(task) > 60:
                task = task[:57] + "..."
            click.echo(f"{'─' * 40}")
            click.echo(f"{matched} ({st}) — {task}")
            click.echo(f"{'─' * 40}")

        if raw:
            log_path = config.log_dir_for_team(team.name) / f"{matched}.log"
            if not log_path.exists():
                click.echo(f"  (no log file)")
            else:
                lines = log_path.read_text().splitlines()
                for line in lines[-tail:]:
                    click.echo(line)
        else:
            output = tmux.capture_pane(matched, lines=tail).rstrip("\n")
            click.echo(output)

        if i < len(resolved) - 1:
            click.echo()


# ── team send-to-worker ─────────────────────────────────────────


@app.command("send-to-worker")
@click.argument("worker_name")
@click.argument("message", nargs=-1, required=True)
def send_to_worker(worker_name: str, message: tuple[str, ...]) -> None:
    """Send a message to a running interactive worker."""
    text = " ".join(message)
    team = config.get_active_team()
    tmux = TmuxOrchestrator(team.tmux_session)
    workers = config.load_workers(team.name)

    matched = names.match_name(worker_name, [w.name for w in workers])
    if not matched:
        raise click.ClickException(f"No worker matching {worker_name!r}")

    tmux.send_keys(matched, text)
    click.echo(f"Sent to {matched}.")


# ── team stop-worker ─────────────────────────────────────────────


@app.command("stop-worker")
@click.argument("worker_name")
def stop_worker(worker_name: str) -> None:
    """Stop a specific worker."""
    team = config.get_active_team()
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
    team = config.get_active_team()
    path = Path(task_file)

    # Sync status first so we have up-to-date worker states
    st = status.get_team_status(team)
    worker_status_map = {w["name"]: w["status"] for w in st["workers"]}

    # Separate tasks into: new (no worker), rerunnable (done worker), running (skip)
    all_pending = taskfile.pending_tasks(path)
    workers = config.load_workers(team.name)
    worker_by_name = {w.name: w for w in workers}

    new_tasks: list[taskfile.TaskEntry] = []
    rerun_tasks: list[taskfile.TaskEntry] = []
    running_skip = 0

    for entry in all_pending:
        if entry.worker_name and entry.worker_name in worker_status_map:
            ws = worker_status_map[entry.worker_name]
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

    if dry_run:
        for entry in to_act:
            wd = entry.working_dir or team.working_dir
            prov = entry.provider or team.provider
            mode = entry.mode or team.worker_mode
            is_rerun = entry in rerun_tasks
            tag = " (rerun)" if is_rerun else ""
            click.echo(f"  - {entry.task}{tag}")
            click.echo(f"    dir={wd}  provider={prov}  mode={mode}")
        return

    tmux = TmuxOrchestrator(team.tmux_session)
    if not tmux.session_exists():
        raise click.ClickException(
            f"tmux session {team.tmux_session!r} not found. Run 'team init' first."
        )

    updates: dict[int, taskfile.TaskEntry] = {}
    spawned = 0
    resumed = 0

    for entry in to_act:
        prov = entry.provider or team.provider
        mode = entry.mode or team.worker_mode
        model = entry.model or team.model
        workdir = entry.working_dir or team.working_dir

        # Check if this is a rerun with an existing worker
        existing_worker = worker_by_name.get(entry.worker_name) if entry.worker_name else None

        if existing_worker and existing_worker.status == "done":
            # Re-run: send the task to the existing worker
            worker_name = existing_worker.name

            if existing_worker.mode == "interactive":
                # Interactive agent is still running — just send the task as input
                tmux.send_keys(worker_name, entry.task)
            elif existing_worker.session_id and prov == "claude":
                # Oneshot with session ID — resume with context
                resume_cmd = agents.build_resume_command(
                    prov, existing_worker.session_id, entry.task,
                )
                tmux.send_keys(worker_name, resume_cmd)
            else:
                # Oneshot without session ID — re-run the full command
                worker_cmd = agents.build_worker_command(
                    provider_name=prov,
                    task=entry.task,
                    mode=mode,
                    model=model,
                    permissions=team.permissions,
                )
                tmux.send_keys(worker_name, worker_cmd)

            existing_worker.status = "running"
            resumed += 1
            click.echo(f"  {worker_name} | {entry.task} (rerun)")
        else:
            # New task — spawn a fresh worker
            existing_names = [w.name for w in workers]
            worker_name = entry.name or names.next_name(existing_names)

            worker_cmd = agents.build_worker_command(
                provider_name=prov,
                task=entry.task,
                mode=mode,
                model=model,
                permissions=team.permissions,
            )

            log_path = config.log_dir_for_team(team.name) / f"{worker_name}.log"
            initial_prompt = entry.task if mode == "interactive" else None
            tmux.spawn_worker(worker_name, worker_cmd, workdir, log_path, initial_prompt=initial_prompt)

            worker = config.WorkerState(
                name=worker_name,
                task=entry.task,
                provider=prov,
                model=model,
                mode=mode,
                tmux_window=worker_name,
            )
            workers.append(worker)
            worker_by_name[worker_name] = worker
            spawned += 1
            click.echo(f"  {worker_name} | {entry.task}")

        # Writeback annotation
        entry.worker_name = worker_name
        entry.worker_status = "running"
        updates[entry.line_number] = entry

    config.save_workers(team.name, workers)
    taskfile.update_task_file(path, updates)

    # Try to deliver pending prompts (agents may need a moment to start)
    import time
    if spawned:
        click.echo("\nWaiting for agents to start...")
        for _ in range(10):
            time.sleep(1)
            log_dir = config.log_dir_for_team(team.name)
            delivered = tmux.deliver_pending_prompts(log_dir)
            if delivered:
                click.echo(f"  Delivered prompts to: {', '.join(delivered)}")
            # Check if all pending prompts are delivered
            pending_dir = log_dir / "pending_prompts"
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
    team = config.get_active_team()
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
        team = config.get_active_team()

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
