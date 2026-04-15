"""Provider-specific agent command builders and system prompt generation."""

from __future__ import annotations

import shlex
import tempfile
from pathlib import Path

from .config import TeamConfig
from .models import describe_provider_flags, get_provider

# ── System prompt ────────────────────────────────────────────────

TEAM_LEAD_SYSTEM_PROMPT = """\
You are the lead agent of team "{team_name}". You coordinate work by delegating \
tasks to worker agents that run in parallel.

## Available Commands (run via Bash)

- `team spawn-worker --task "description" --name <short-name> [--mode oneshot|interactive] [--provider claude|codex|gemini] [--resume-session <session-id>]`
  Spawn a new worker agent. Always provide --name with a short (1-2 word, \
kebab-case) name that describes the task, e.g. "fix-auth", "add-tests", \
"update-docs". Use "interactive" (default) for tasks needing back-and-forth, \
"oneshot" for fire-and-forget tasks. Use --resume-session to continue an \
existing Claude or Gemini session.

- `team status`
  Check the status of all workers (running/done/error + elapsed time).

- `team send-to-worker <name> "message"`
  Send a follow-up message to a running interactive worker.

- `team logs <name>`
  View a worker's recent output.

- `team stop-worker <name>`
  Stop a specific worker.

- `team clear`
  Remove completed workers from the status list. Use after reviewing done \
workers to keep the status table clean.

- `team run <file>`
  Spawn workers from a markdown task file.

- `team wait`
  Block until all running workers are done. Polls internally — uses one \
tool call instead of repeated `team status` checks. Always prefer this \
over polling `team status` in a loop.

## Guidelines

- Break large tasks into independent, well-scoped subtasks.
- Assign clear, self-contained prompts to each worker — include file paths, \
context, and acceptance criteria.
- Use interactive mode (default) for most tasks; oneshot mode for simple \
fire-and-forget tasks.
- After spawning workers, use `team wait` to block until they finish. \
Do NOT poll `team status` in a loop — that wastes tokens.
- Use `team status` for a one-time check. Use `team logs <name>` to review output.
- Do not spawn more than {max_workers} workers at once.
- Workers operate in: {working_dir}
- When all workers are done, synthesize results and report back to the user.
"""


WORKER_SYSTEM_PROMPT = """\
You are a worker agent in team "{team_name}". Focus only on the task you are given.

## Rules

- NEVER start, attach to, or interact with tmux sessions. You are already running \
inside tmux — creating nested sessions will break the orchestration.
- NEVER run `team` CLI commands (team spawn-worker, team init, etc.). Only the team \
lead manages workers.
- Work within your assigned directory: {working_dir}
- Complete your task and report results clearly.
"""


def build_worker_system_prompt(team_name: str, working_dir: str) -> str:
    """Generate the system prompt for a worker agent."""
    return WORKER_SYSTEM_PROMPT.format(
        team_name=team_name,
        working_dir=working_dir,
    )


def build_team_lead_system_prompt(config: TeamConfig) -> str:
    """Generate the system prompt for the team lead agent."""
    return TEAM_LEAD_SYSTEM_PROMPT.format(
        team_name=config.name,
        max_workers=config.max_workers,
        working_dir=config.working_dir,
    )


def write_system_prompt_file(config: TeamConfig) -> Path:
    """Write the team lead system prompt to a temp file. Returns the path."""
    prompt = build_team_lead_system_prompt(config)
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", prefix="team-lead-prompt-", delete=False
    )
    f.write(prompt)
    f.close()
    return Path(f.name)


# ── Command builders ─────────────────────────────────────────────


def _build_command_with_logging(
    parts: list[str],
    provider_name: str,
    mode: str,
    log_path: Path | None,
) -> str:
    """Build a shell command string with native CLI logging.

    Interactive: stderr redirected to log (TUI stays on stdout).
    Oneshot: both stdout and stderr redirected to log.
    Environment variables for providers that use them (e.g. RUST_LOG).
    """
    provider = get_provider(provider_name)

    # Add provider-specific logging flags
    if mode == "oneshot":
        parts.extend(provider.log_args_oneshot)
    else:
        parts.extend(provider.log_args_interactive)

    cmd = shlex.join(parts)

    # Prepend env vars if needed
    if provider.log_env:
        env_prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in provider.log_env.items())
        cmd = f"{env_prefix} {cmd}"

    # Append output redirection
    if log_path:
        quoted = shlex.quote(str(log_path))
        if mode == "oneshot":
            cmd = f"{cmd} > {quoted} 2>&1"
        else:
            cmd = f"{cmd} 2>> {quoted}"

    return cmd


def build_lead_command(
    config: TeamConfig,
    system_prompt_file: Path,
    log_path: Path | None = None,
) -> str:
    """Build the shell command to start the team lead agent (interactive)."""
    provider = get_provider(config.provider)
    parts: list[str] = [provider.cli_command]
    parts.extend(lead_runtime_flags(config))

    # System prompt injection
    if provider.system_prompt_file_flag:
        parts.extend([provider.system_prompt_file_flag, str(system_prompt_file)])
    elif provider.system_prompt_flag:
        prompt = build_team_lead_system_prompt(config)
        parts.extend([provider.system_prompt_flag, prompt])

    return _build_command_with_logging(parts, config.provider, "interactive", log_path)


def build_worker_command(
    provider_name: str,
    task: str,
    mode: str = "interactive",
    model: str | None = None,
    permissions: str = "auto",
    team_name: str = "",
    working_dir: str = "",
    log_path: Path | None = None,
) -> str:
    """Build the shell command to start a worker agent."""
    provider = get_provider(provider_name)
    parts: list[str] = [provider.cli_command]
    parts.extend(worker_runtime_flags(
        provider_name,
        mode=mode,
        model=model,
        permissions=permissions,
    ))

    # System prompt for worker context
    if provider.system_prompt_flag:
        prompt = build_worker_system_prompt(team_name, working_dir)
        parts.extend([provider.system_prompt_flag, prompt])

    # For oneshot mode, the task is the positional prompt argument
    if mode == "oneshot":
        parts.append(task)

    return _build_command_with_logging(parts, provider_name, mode, log_path)


def build_resume_command(
    provider_name: str,
    session_id: str,
    prompt: str,
    log_path: Path | None = None,
    mode: str = "oneshot",
) -> str:
    """Build a command to resume a prior agent session with a follow-up.

    In oneshot mode the prompt is passed as a positional argument.
    In interactive mode the agent opens an interactive session continuing
    from the prior conversation (prompt is sent separately via tmux).
    """
    provider = get_provider(provider_name)
    if not provider.resume_flag:
        raise ValueError(f"Provider {provider_name!r} does not support session resume")

    parts: list[str] = [provider.cli_command]
    if mode == "oneshot":
        parts.extend(provider.oneshot_args)
    else:
        parts.extend(provider.interactive_args)
    parts.extend([provider.resume_flag, session_id])
    if mode == "oneshot":
        parts.append(prompt)
    return _build_command_with_logging(parts, provider_name, mode, log_path)


def lead_runtime_flags(config: TeamConfig) -> list[str]:
    """Return the provider/runtime flags used for the lead session."""
    return describe_provider_flags(
        config.provider,
        model=config.model,
        permissions=config.permissions,
        mode="interactive",
    )


def worker_runtime_flags(
    provider_name: str,
    *,
    mode: str,
    model: str | None,
    permissions: str,
) -> list[str]:
    """Return the provider/runtime flags used for a worker launch."""
    return describe_provider_flags(
        provider_name,
        model=model,
        permissions=permissions,
        mode=mode,
    )
