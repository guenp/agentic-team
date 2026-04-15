# Getting Started

## Prerequisites

- **Python 3.13+**
- **tmux**

    ```bash
    # macOS
    brew install tmux

    # Ubuntu / Debian
    sudo apt install tmux
    ```

- At least one supported provider CLI on `PATH`: `claude`, `codex`, or `gemini`
- Provider authentication completed outside `agentic-team`

`agentic-team` does not install or log in provider CLIs for you. See [Providers](providers.md) for the exact binaries and behavior differences.

## Install

```bash
pip install agentic-team
```

Or from source with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/guenp/agentic-team.git
cd agentic-team
uv sync
```

## Start your first team

```bash
team init myproject --provider claude --working-dir ~/repos/myproject
```

This does four things:

1. saves `myproject` under `~/.agentic-team/teams/`
2. makes it the active team
3. creates a timestamped log directory under `~/.agentic-team/logs/myproject/`
4. starts the lead agent in tmux session `team-myproject`

Send the lead a prompt:

```bash
team "fix the auth bug and add tests for the login flow"
```

Or attach directly:

```bash
team attach
```

## Check progress

```bash
team status
team logs
team standup
team attach --multi
```

What each command is best for:

- `team status` refreshes worker state and prints the full table.
- `team logs` shows the current session logs, with tmux-pane fallback for interactive TUIs.
- `team standup` asks the lead to write a markdown summary for every worker.
- `team attach --multi` joins live worker panes into one tiled dashboard.

## Run a task file

```markdown
## ~/repos/backend
- [ ] Fix the login bug
- [ ] Add regression tests (provider: codex, mode: oneshot)
```

```bash
team run tasks.md
team sync tasks.md
```

Task-file syntax, rerun rules, and annotations are documented in [Task Files](task-files.md).

## Work with more than one team

```bash
team list
team -T other-team status
TEAM_NAME=other-team team logs lead
```

`team init` switches the active team to the name you just created. Use `-T` or `TEAM_NAME` when you want to inspect another team without switching the active symlink. See [Managing Multiple Teams](multiple-teams.md) for the full workflow.

## Troubleshooting

If something looks wrong at runtime, start with:

```bash
team list
team logs lead
team status lead -v
```

The full runtime paths and recovery steps are in [Operations](operations.md).

## Next pages

- [Providers](providers.md)
- [Commands](commands.md)
- [Task Files](task-files.md)
- [Examples](examples.md)
- [Operations](operations.md)
