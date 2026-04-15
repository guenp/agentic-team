"""Provider-specific agent command builders and system prompt generation."""

from __future__ import annotations

import shlex
import tempfile
from pathlib import Path

from .config import TeamConfig
from .models import get_provider

# ── System prompt ────────────────────────────────────────────────

TEAM_LEAD_SYSTEM_PROMPT = """\
You are the lead agent of team "{team_name}". You coordinate work by delegating \
tasks to worker agents that run in parallel.

## Available Commands (run via Bash)

- `team spawn-worker --task "description" --name <short-name> [--mode oneshot|interactive] [--provider claude|codex|gemini]`
  Spawn a new worker agent. Always provide --name with a short (1-2 word, \
kebab-case) name that describes the task, e.g. "fix-auth", "add-tests", \
"update-docs". Use "interactive" (default) for tasks needing back-and-forth, \
"oneshot" for fire-and-forget tasks.

- `team status`
  Check the status of all workers (running/done/error + elapsed time).

- `team send-to-worker <name> "message"`
  Send a follow-up message to a running interactive worker.

- `team logs <name>`
  View a worker's recent output.

- `team stop-worker <name>`
  Stop a specific worker.

## Guidelines

- Break large tasks into independent, well-scoped subtasks.
- Assign clear, self-contained prompts to each worker — include file paths, \
context, and acceptance criteria.
- Use interactive mode (default) for most tasks; oneshot mode for simple \
fire-and-forget tasks.
- Monitor progress with `team status` and review output with `team logs <name>`.
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


def build_lead_command(
    config: TeamConfig,
    system_prompt_file: Path,
) -> str:
    """Build the shell command to start the team lead agent (interactive)."""
    provider = get_provider(config.provider)
    parts: list[str] = [provider.cli_command]

    if config.model:
        parts.extend(["--model", config.model])

    parts.extend(provider.interactive_args)

    # Permission mode (claude-specific)
    if config.provider == "claude" and config.permissions != "default":
        parts.extend(["--permission-mode", config.permissions])

    # System prompt injection
    if provider.system_prompt_file_flag:
        parts.extend([provider.system_prompt_file_flag, str(system_prompt_file)])
    elif provider.system_prompt_flag:
        prompt = build_team_lead_system_prompt(config)
        parts.extend([provider.system_prompt_flag, prompt])

    return shlex.join(parts)


def build_worker_command(
    provider_name: str,
    task: str,
    mode: str = "interactive",
    model: str | None = None,
    permissions: str = "auto",
    team_name: str = "",
    working_dir: str = "",
) -> str:
    """Build the shell command to start a worker agent."""
    provider = get_provider(provider_name)
    parts: list[str] = [provider.cli_command]

    if model:
        parts.extend(["--model", model])

    if mode == "oneshot":
        parts.extend(provider.oneshot_args)
    else:
        parts.extend(provider.interactive_args)

    # Permission mode (claude-specific)
    if provider_name == "claude" and permissions != "default":
        parts.extend(["--permission-mode", permissions])

    # System prompt for worker context
    if provider.system_prompt_flag:
        prompt = build_worker_system_prompt(team_name, working_dir)
        parts.extend([provider.system_prompt_flag, prompt])

    # For oneshot mode, the task is the positional prompt argument
    if mode == "oneshot":
        parts.append(task)

    return shlex.join(parts)


def build_resume_command(
    provider_name: str,
    session_id: str,
    prompt: str,
) -> str:
    """Build a command to resume a prior agent session with a follow-up."""
    provider = get_provider(provider_name)
    if not provider.resume_flag:
        raise ValueError(f"Provider {provider_name!r} does not support session resume")

    parts: list[str] = [provider.cli_command]
    parts.extend(provider.oneshot_args)
    parts.extend([provider.resume_flag, session_id])
    parts.append(prompt)
    return shlex.join(parts)
