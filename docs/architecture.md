# Architecture

## Overview

agentic-team uses tmux as the execution layer for running multiple AI agents in parallel. Each agent runs in its own tmux window within a shared session.

```
team CLI
  │
  ├── config.py        State persistence (TOML)
  ├── agents.py        Command builders + system prompts
  ├── tmux.py          TmuxOrchestrator (all tmux interaction)
  ├── status.py        Worker completion detection
  ├── taskfile.py      Markdown task file parser
  ├── models.py        Provider registry
  ├── names.py         Worker name generator
  └── cli.py           Click entry point
```

## State management

All state lives under `~/.agentic-team/`:

| Directory | Contents |
|-----------|----------|
| `teams/` | Team configuration files (`<name>.toml`) |
| `state/` | Worker state per team (`<name>/workers.toml`) |
| `logs/` | Raw pipe-pane output per worker |
| `active` | Symlink to the active team's state directory |

State is stored in TOML using `tomllib` (read) and `tomli_w` (write).

## Tmux interaction

`TmuxOrchestrator` centralizes all tmux subprocess calls:

- **Session lifecycle**: `new-session`, `kill-session`, `has-session`
- **Window management**: `new-window`, `kill-window`, `list-windows`
- **I/O**: `send-keys` (with `-l` literal flag), `capture-pane`
- **Logging**: `pipe-pane` to log files
- **Attach**: `os.execvp` for proper terminal handoff
- **Multi-attach**: Creates a tiled dashboard window with `split-window` + `select-layout tiled`, each pane running a capture loop

### Pending prompt delivery

Interactive workers need time to start before they can accept input. The orchestrator implements a queue:

1. `spawn_worker()` writes the task to a pending prompt file
2. `deliver_pending_prompts()` polls capture-pane for readiness indicators (e.g., Claude Code's `❯` prompt)
3. Once detected, the prompt is sent via `send-keys` and the pending file is removed

## Completion detection

### Oneshot workers

The agent command exits but the tmux pane drops to a shell prompt. Detection strategy:

1. Capture the last 80 lines of the pane
2. Find the **last** agent command invocation (avoids false positives from prior runs in scrollback)
3. Check for a JSON result (`"type":"result"`) or shell prompt (`$`, `%`, `#`, `❯`) after it

### Interactive workers

The agent stays running. Detection strategy:

1. Check if `"esc to interrupt"` appears in Claude Code's status bar -- if present, the agent is actively working
2. Verify the task text appears in the pane (confirming it was sent)
3. Look for agent output markers (`⏺`, `⎿`) after the task line

## Provider abstraction

`models.py` defines a `ProviderConfig` dataclass for each supported agent CLI:

| Field | Purpose |
|-------|---------|
| `cli_command` | The binary name (`claude`, `codex`, `gemini`) |
| `interactive_args` | Flags for interactive mode |
| `oneshot_args` | Flags for one-shot mode |
| `system_prompt_flag` | How to inject a system prompt |
| `system_prompt_file_flag` | File-based system prompt injection |
| `resume_flag` | Session resumption flag (Claude only) |

## CLI routing

`TeamGroup` subclasses `click.Group` to enable bare `team "prompt"` syntax. If the first argument isn't a known subcommand, it checks for typos using `difflib.get_close_matches` before routing to the `send` command.
