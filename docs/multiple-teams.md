# Managing Multiple Teams

`agentic-team` can keep several team configs on disk at the same time. The selection rules come from the global `--team/-T` option in `src/agentic_team/cli.py` and the active-team symlink logic in `src/agentic_team/config.py`.

## How team selection works

- `team init <name>` saves the new config and makes that team active.
- Commands that operate on an existing team use the active team by default.
- `-T, --team <name>` overrides the active team for one command.
- `TEAM_NAME=<name>` does the same override through the environment.
- `team stop <name>` stops a named team without switching the active team first.

The active team is stored as the symlink `~/.agentic-team/active -> ~/.agentic-team/state/<name>`.

## See what exists

```bash
team list
```

`team list` reads every config under `~/.agentic-team/teams/*.toml` and reports:

- the team name
- whether it is the active team
- the configured provider
- whether the tmux session is currently `running` or `stopped`

## Target a different team for one command

```bash
team -T docs status
team -T docs logs lead
team -T backend attach -w lead
```

`-T` does not rewrite the active-team symlink. It only changes the team used by that single invocation.

## Use `TEAM_NAME` in scripts

```bash
TEAM_NAME=docs team status
TEAM_NAME=docs team logs fix-auth
TEAM_NAME=backend team standup --timeout 180
```

This is the same override as `-T/--team`, just easier to compose in shell scripts.

## Typical multi-team workflow

```bash
# Start two teams
team init docs --provider claude --working-dir ~/repos/docs
team init backend --provider codex --working-dir ~/repos/backend

# `backend` is now active because it was initialized last
team status

# Check the other team without switching the active link
team -T docs status
TEAM_NAME=docs team logs lead
```

## Stale teams and cleanup

A team can become stale when its config still exists on disk but the tmux session is gone.

How to handle that today:

- Run `team list` to confirm it shows as `stopped`.
- If you want to reuse the same name, run `team init <same-name> ...`. The current code prints `Overwriting stale config for '<name>'` when the config exists but the tmux session does not.
- If the tmux session is still alive, stop it first with `team stop <name>`.

There is no `team delete` command. To fully purge a stale team, remove its files manually after making sure the tmux session is not running:

- `~/.agentic-team/teams/<name>.toml`
- `~/.agentic-team/state/<name>/`
- `~/.agentic-team/logs/<name>/`

## Common pitfalls

- `team stop` without a name stops the active team, not whichever team you last inspected with `-T`.
- `TEAM_NAME` and `-T` only affect commands that load an existing team. They do not change what `team init` writes.
- `team list` is config-driven. A team stays listed after `team stop` until you remove its files manually.
