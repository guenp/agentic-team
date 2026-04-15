# Operations and Troubleshooting

This page covers the runtime files and recovery paths that exist in the current implementation.

## Runtime locations

All runtime state lives under `~/.agentic-team/`:

| Path | What it stores |
|------|----------------|
| `teams/<name>.toml` | Team configuration such as provider, model, worker mode, permissions, and working directory |
| `state/<name>/workers.toml` | Worker records with provider, mode, status, session ID, and timestamps |
| `state/<name>/pending_prompts/` | Queued initial prompts for interactive workers that have not reached a ready screen yet |
| `state/<name>/multi_targets` | Pane join order for `team attach --multi` |
| `state/<name>/standup.md` | Last standup report written by `team standup` |
| `logs/<name>/<timestamp>/` | Per-session log directory created by `team init` and reused by later worker launches |
| `logs/<name>/current` | Symlink to the current session log directory |
| `active` | Symlink to the active team's state directory |

## Real log paths

`team init` creates a timestamped session log directory such as:

```text
~/.agentic-team/logs/myproject/20260415-003621/
```

Within that directory you will typically see:

```text
lead.log
fix-auth.log
add-tests.log
```

New workers use the current session directory. If no current directory exists, the CLI creates one before launching the worker.

## How `team logs` actually works

`team logs` is implemented in `src/agentic_team/cli.py`.

For each target worker, it does this:

1. Resolve the name by prefix match, also allowing `lead`.
2. Look for `~/.agentic-team/logs/<team>/current/<target>.log`.
3. If that file exists and is non-empty, print the last `--tail` lines from it.
4. Otherwise, fall back to tmux `capture-pane` for the live pane content.

Implications:

- `team logs` has no `--raw` flag in the current code.
- `team logs` with no arguments already means "all workers".
- `team logs --all` is the explicit version of the same behavior.
- `team logs lead` works even though the lead is not part of the worker list.
- Interactive TUI agents may have sparse log files because the visible screen is not always written to stderr; the capture-pane fallback is expected.

## How to inspect the lead

Use whichever view is most useful for the problem:

```bash
team logs lead
team status lead -v
team attach -w lead
```

Notes:

- `team status lead -v` streams the lead pane live.
- `team status lead` without `-v` still prints the normal full team table; the `WORKER_NAME` argument only affects verbose mode.
- `team standup` asks the lead to write `~/.agentic-team/state/<team>/standup.md`, then either renders that file or falls back to pane capture if the file never appears.

## Pre-flight check

Run `team doctor` to verify tmux, provider auth, and (if applicable) the active lead session in a single command:

```bash
team doctor
team doctor --provider claude
```

This is the fastest way to rule out environment issues before debugging further.

## Common recovery steps

### `No active team. Run 'team init <name>' to create one.`

Either:

- start a team with `team init <name> ...`, or
- target an existing one explicitly with `team -T <name> ...`, or
- export `TEAM_NAME=<name>` for the command you are running

Use `team list` if you are not sure which teams already exist.

### `tmux session 'team-<name>' not found`

The config exists, but the tmux session is gone.

Recovery:

1. Confirm with `team list` that the team shows as `stopped`.
2. Reinitialize it with the same name: `team init <name> ...`
3. If a tmux session is still alive under that name, stop it first with `team stop <name>`

`team init` already handles the common stale-config case by overwriting the saved config when the session does not exist.

### `No worker slots available`

`team run` computes available slots as:

```text
(--limit or team.max_workers) - currently running workers
```

Recovery options:

- wait for active workers with `team wait`
- clear completed workers with `team clear`
- initialize a new team with a higher `--max-workers`
- rerun with a larger `--limit` if you explicitly set one too low

### A worker looks idle but still says `running`

Run `team status` again. Status refresh is what:

- delivers queued initial prompts to newly started interactive workers
- re-checks pane liveness
- extracts Claude oneshot session IDs after completion

If the worker is truly finished, `team clear` removes it from the saved worker list and kills any orphaned window left behind.

### `team logs` is empty or incomplete

This usually means the provider TUI is not writing much useful output to the log file.

Try:

```bash
team logs <worker>
team status <worker> -v
team attach -w <worker>
```

The second and third options read directly from the tmux pane instead of depending on the log file.

### `Cannot resume ... session_id=None`

Current resume rules:

- interactive workers can always receive another prompt while their pane is alive
- oneshot resume needs a stored `session_id`
- automatic `session_id` capture only exists for Claude oneshot workers

If no session ID is available, rerun the task as a fresh command instead of a session resume.

### Multi-pane dashboard looks stale

`team attach --multi` stores pane join state in `state/<team>/multi_targets`.

To get back to normal windows, run:

```bash
team attach
```

Plain `team attach` calls `break_multi(...)` first and restores the original windows before attaching.
