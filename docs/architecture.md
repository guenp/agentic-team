# Architecture

## Overview

`agentic-team` uses tmux as the execution layer and TOML files for durable state.

```text
team CLI
  ├── cli.py         Click entry point and command orchestration
  ├── config.py      Team config, worker state, log/session paths
  ├── agents.py      Provider-specific command builders and system prompts
  ├── tmux.py        All tmux subprocess interaction
  ├── status.py      Worker completion detection and state refresh
  ├── taskfile.py    Markdown task-file parsing and writeback
  ├── models.py      Provider registry
  └── names.py       Worker naming and prefix matching
```

## State model

All state lives under `~/.agentic-team/`:

| Path | Purpose |
|------|---------|
| `teams/<name>.toml` | Saved `TeamConfig` |
| `state/<name>/workers.toml` | Saved `WorkerState` list |
| `state/<name>/pending_prompts/` | Interactive worker prompts waiting for the pane to become ready |
| `state/<name>/multi_targets` | Pane join order for `team attach --multi` |
| `state/<name>/standup.md` | Standup report written by the lead |
| `logs/<name>/<timestamp>/` | Session log files |
| `logs/<name>/current` | Symlink to the active session log directory |
| `active` | Symlink to the active team's state directory |

State serialization uses `tomllib` for reads and `tomli_w` for writes.

## Tmux layer

`TmuxOrchestrator` centralizes all tmux calls:

- session lifecycle: `new-session`, `has-session`, `kill-session`
- window lifecycle: `new-window`, `kill-window`, `list-windows`
- input/output: `send-keys`, `capture-pane`
- dashboard mode: `join-pane`, `break-pane`, `select-layout tiled`
- terminal handoff: `os.execvp("tmux", ...)` for attach

Two implementation details matter for runtime behavior:

1. Window renaming is disabled so status tracking can rely on stable names.
2. `window-size` is forced to `smallest` so attached clients resize all windows consistently.

## Logging model

The current code does not use `pipe-pane`.

Instead, provider commands are built with native logging flags and shell redirection in `agents._build_command_with_logging(...)` inside `src/agentic_team/agents.py`:

- interactive commands append stderr to `<session-log-dir>/<worker>.log`
- oneshot commands redirect stdout and stderr to the log file
- providers can also contribute environment variables such as Codex's `RUST_LOG`

User-facing log inspection happens in `team logs` inside `src/agentic_team/cli.py`, which prefers the log file and falls back to tmux `capture-pane`.

## Interactive prompt delivery

Interactive workers are not given their task immediately. The flow is:

1. `spawn_worker(...)` starts the provider CLI in a new tmux window.
2. If the worker is interactive, the task is written to `state/<team>/pending_prompts/<worker>`.
3. `deliver_pending_prompts(...)` checks `capture-pane` for provider-specific readiness strings:
   - `Claude Code`
   - `OpenAI Codex`
   - `Gemini CLI`
   - `Type your message`
4. Once ready, tmux sends the task text and removes the pending file.

This is why `team status` can change a newly launched worker from "waiting to start" into active work: status refresh calls `deliver_pending_prompts(...)`.

## Completion detection

### Oneshot workers

`status._is_oneshot_done(...)` uses pane capture, not just process exit:

1. capture the last 80 lines
2. find the last provider command invocation in scrollback
3. inspect only the lines after that command
4. mark the worker done when either:
   - Claude emits `"type":"result"` after the last command, or
   - a shell prompt appears after the command output

### Interactive workers

`status._is_interactive_idle(...)` is provider-specific:

- Claude: idle when the tail no longer shows `esc to inter` and the pane has enough non-empty content
- Codex: running while `Working (` is visible; done when `Worked for` or an idle prompt is visible
- Gemini: done when the tail shows `Type your message` and the pane has enough prior output

## Provider abstraction

`src/agentic_team/models.py` defines a `ProviderConfig` with:

- CLI binary name
- model aliases
- interactive and oneshot argument lists
- optional resume flag
- optional system-prompt flags
- provider logging flags and logging environment variables

Current provider-specific behavior is summarized in [Providers](providers.md).

## CLI routing

`TeamGroup` extends `click.Group` so a bare prompt such as:

```bash
team "review the workers and summarize progress"
```

is rewritten to:

```bash
team send "review the workers and summarize progress"
```

The router checks for close subcommand typos first, so `team stats` raises a usage error instead of silently sending `"stats"` to the lead.

## User-facing operations

Architecture explains how the pieces fit together. For actual runtime inspection and recovery commands, use [Operations](operations.md).
