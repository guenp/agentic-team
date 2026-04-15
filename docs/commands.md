# Commands

## Team lifecycle

### `team init`

Initialize a new team and start the team lead agent.

```bash
team init <name> [options]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--provider`, `-p` | `claude` | Team lead agent provider (`claude`, `codex`, `gemini`) |
| `--model`, `-m` | *(provider default)* | Model name (e.g. `opus`, `o4-mini`) |
| `--working-dir`, `-C` | `.` | Working directory for agents |
| `--max-workers` | `6` | Maximum concurrent workers |
| `--worker-mode` | `interactive` | Default worker mode (`oneshot` or `interactive`) |
| `--permissions` | `auto` | Permission mode for all agents |

### `team stop`

Stop a team and kill its tmux session.

```bash
team stop [<name>]
```

If no name is given, stops the active team.

### `team list`

List all teams with their status.

```bash
team list
```

---

## Interacting with the lead

### `team send`

Send a prompt to the team lead agent. Bare prompts are automatically routed to this command.

```bash
# These are equivalent:
team "your prompt here"
team send "your prompt here"
```

### `team attach`

Attach to the team's tmux session.

```bash
team attach [--window <name>]
team attach --multi
```

| Option | Description |
|--------|-------------|
| `--window`, `-w` | Jump directly to a worker's window. Supports prefix matching. |
| `--multi`, `-m` | Join all workers into a single tiled window. |

`team attach` always shows one worker per tab. `team attach --multi` always shows all workers in one tiled view. Switching between the two is seamless.

!!! tip
    Use `Ctrl-b n` / `Ctrl-b p` to switch between windows inside tmux.

---

## Managing workers

### `team spawn-worker`

Spawn a new worker agent.

```bash
team spawn-worker --task "description" [options]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--task`, `-t` | *(required)* | Task description |
| `--mode` | *(team default)* | `oneshot` or `interactive` |
| `--provider` | *(team default)* | Agent provider |
| `--model` | *(team default)* | Model override |
| `--name`, `-n` | *(auto-generated)* | Custom worker name |
| `--working-dir`, `-C` | *(team default)* | Working directory for this worker |

### `team status`

Show the status of all workers.

```bash
team status
```

Displays worker name, provider, mode, status (`running`/`done`), elapsed time, and task description.

### `team logs`

View worker output via tmux capture-pane.

```bash
team logs [<name>] [--all] [--tail 50] [--raw]
```

- No arguments: shows all workers with headers
- With a name: shows that specific worker
- `--raw`: reads the pipe-pane log file instead of capture-pane
- `--tail`, `-n`: number of lines to capture (default 50)

### `team send-to-worker`

Send a follow-up message to a running interactive worker.

```bash
team send-to-worker <name> "message"
```

### `team resume`

Resume a completed worker with a follow-up prompt. For oneshot Claude workers, this uses `--resume` with the captured session ID. For interactive workers, sends the prompt directly.

```bash
team resume <name> "follow-up prompt"
```

### `team stop-worker`

Stop a specific worker.

```bash
team stop-worker <name>
```

---

## Task files

### `team run`

Spawn workers from a markdown task file.

```bash
team run <file> [--dry-run] [--rerun] [--limit N]
```

| Option | Description |
|--------|-------------|
| `--dry-run` | Preview what would be spawned |
| `--rerun` | Re-run completed tasks |
| `--limit`, `-l` | Max tasks to spawn (defaults to team max_workers) |

### `team sync`

Update a task file's checkboxes from current worker status.

```bash
team sync <file>
```
