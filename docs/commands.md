# Commands

This page mirrors the current Click surface in `src/agentic_team/cli.py`.

## Global options

Top-level usage:

```text
team [OPTIONS] COMMAND [ARGS]...
```

| Option | Meaning |
|--------|---------|
| `--version` | Show the installed `agentic-team` version |
| `-T, --team TEXT` | Use a specific team instead of the active team |
| `TEAM_NAME=<name>` | Environment-variable form of `--team` |
| `--help` | Show top-level help |

Notes:

- `team "prompt"` is routed to `team send "prompt"` by the custom Click group.
- If the bare word looks like a typo of a real subcommand, the CLI raises a usage error instead of silently routing it to `send`.

## Team lifecycle

### `team init`

```text
team init [OPTIONS] NAME
```

| Option | Meaning |
|--------|---------|
| `-p, --provider [claude\|codex\|gemini]` | Team lead provider. Default `claude`. |
| `-m, --model TEXT` | Lead model override. No default (uses the provider's own default). |
| `--worker-mode [oneshot\|interactive]` | Default mode for new workers. Default `interactive`. |
| `--permissions [auto\|default\|dangerously-skip-permissions]` | Permission mode saved in team config. Default `auto`. |
| `--max-workers INTEGER` | Maximum concurrent workers. Default `6`. |
| `-C, --working-dir DIRECTORY` | Default working directory for lead and workers. Default `.` (current directory). |

Behavior notes:

- `team init` saves the config, makes it active, creates a timestamped log directory, and starts the lead in tmux.
- If the team config exists but the tmux session does not, `team init` overwrites that stale config.
- If the tmux session is still alive, `team init` fails until you stop it.

### `team list`

```text
team list
```

Lists every saved team as:

```text
<name>[(active)] — <provider> — running|stopped
```

### `team stop`

```text
team stop [NAME]
```

- With `NAME`, stops that team.
- Without `NAME`, stops the active team.
- If you stop the active team, the `~/.agentic-team/active` symlink is cleared.

## Talking to the lead

### `team send`

```text
team send PROMPT...
```

Equivalent forms:

```bash
team "review the open workers and summarize progress"
team send "review the open workers and summarize progress"
```

### `team attach`

```text
team attach [OPTIONS]
```

| Option | Meaning |
|--------|---------|
| `-w, --window TEXT` | Select a specific window before attaching |
| `-m, --multi` | Join live worker panes into a tiled dashboard |

Behavior notes:

- `--window` supports prefix matching against worker names and `lead`.
- Plain `team attach` first breaks any existing multi-pane layout and restores normal windows.
- `team attach --multi` only includes workers that still have a live tmux window.

### `team standup`

```text
team standup [OPTIONS]
```

| Option | Meaning |
|--------|---------|
| `--timeout INTEGER` | Maximum seconds to wait for `standup.md` |
| `-v, --verbose` | Stream the lead pane live while waiting |

Behavior notes:

- The CLI asks the lead to write `~/.agentic-team/state/<team>/standup.md`.
- If the file appears, the CLI renders it as markdown.
- If the lead never writes the file, the CLI falls back to the captured lead pane.

## Worker management

### `team spawn-worker`

```text
team spawn-worker [OPTIONS]
```

| Option | Meaning |
|--------|---------|
| `-t, --task TEXT` | Task description for the worker. Required. |
| `--mode [oneshot\|interactive]` | Worker mode. Defaults to the team's `worker_mode`. |
| `--provider [claude\|codex\|gemini]` | Worker provider. Defaults to the team's provider. |
| `--model TEXT` | Model override for this worker |
| `-n, --name TEXT` | Custom worker name |
| `-C, --working-dir DIRECTORY` | Working directory for this worker |
| `-r, --resume-session TEXT` | Seed the worker from an existing Claude or Gemini session |

Behavior notes:

- `--resume-session` is rejected for providers without a resume flag.
- Interactive workers start first and receive their task once the pane looks ready.
- Oneshot workers get the task as part of the command line.

### `team status`

```text
team status [OPTIONS] [WORKER_NAME]
```

Displays worker name, provider, status (`running`/`waiting`/`done`), elapsed time, task source, and task description.

| Option | Meaning |
|--------|---------|
| `-v, --verbose` | Live tail of worker or lead output. Press `q` to quit. |

Behavior notes:

- Plain `team status` always prints the full team table.
- `WORKER_NAME` only changes behavior when you also pass `-v`.
- In verbose mode, `WORKER_NAME` can target a worker prefix or `lead`.

### `team logs`

```text
team logs [OPTIONS] [WORKER_NAME]
```

| Option | Meaning |
|--------|---------|
| `-n, --tail INTEGER` | Number of lines to show |
| `-a, --all` | Show every worker instead of a single target |

Behavior notes:

- No `WORKER_NAME` means "all workers".
- `team logs lead` is supported.
- The command prefers the current session log file and falls back to tmux `capture-pane` when the file is missing or empty.
- There is no `--raw` flag in the current CLI.

### `team send-to-worker`

```text
team send-to-worker WORKER_NAME MESSAGE...
```

Sends text directly to a running interactive worker. `WORKER_NAME` supports prefix matching.

### `team resume`

```text
team resume WORKER_NAME PROMPT...
```

Resume rules:

- Interactive workers receive the prompt directly through tmux.
- Oneshot workers resume only if their saved worker state has a `session_id`.
- If there is no stored `session_id`, the command fails with the current worker status, mode, and session ID.

### `team stop-worker`

```text
team stop-worker WORKER_NAME
```

Kills the worker window and marks that worker `done` in saved state.

### `team wait`

```text
team wait [OPTIONS]
```

| Option | Meaning |
|--------|---------|
| `-t, --timeout INTEGER` | Maximum seconds to wait. Default `600`. |
| `-i, --interval INTEGER` | Poll interval in seconds. Default `15`. |

The command prints the status table immediately, then only reprints it when a worker's status changes.

### `team clear`

```text
team clear
```

Removes completed workers from saved state and kills their tmux windows. It also cleans up orphaned tmux windows that are not tracked in the worker list.

## Task-file commands

### `team run`

```text
team run [OPTIONS] TASK_FILE
```

| Option | Meaning |
|--------|---------|
| `-l, --limit INTEGER` | Maximum total tasks allowed for this run, including workers already running |
| `--dry-run` | Show resolved task details without spawning anything |
| `--rerun` | Re-run completed tasks by reusing their existing worker slots when possible |

Behavior notes:

- The file format is documented in [Task Files](task-files.md).
- Only unchecked tasks are considered.
- The effective spawn count is `(limit or team.max_workers) - currently running workers`.
- Matching is annotation-first (`← worker-name`), then exact task text.

### `team sync`

```text
team sync TASK_FILE
```

Updates task annotations and ticks completed tasks to `[x]`. `team sync` only updates lines that already carry a `← worker-name` annotation.

## Name matching

Prefix matching is implemented by `src/agentic_team/names.py`. These commands accept worker-name prefixes:

- `team attach -w <prefix>`
- `team logs <prefix>`
- `team send-to-worker <prefix> ...`
- `team resume <prefix> ...`
- `team stop-worker <prefix>`
- `team status <prefix> -v`
