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

## Verify your environment

Before creating a team, confirm that tmux and your chosen provider are ready:

```bash
team doctor --provider claude
```

`team doctor` checks that tmux is installed, the provider CLI is on `PATH`, and authentication is valid. If you already have an active team it also verifies the lead session is running.

## Start your first team

```bash
team init myproject --provider claude --working-dir ~/repos/myproject
```

If exactly one provider is installed and authenticated, `--provider` can be omitted and `team init` will auto-detect it.

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

## Talk to the lead

The primary way to use `agentic-team` is **conversational delegation** — you give the lead agent high-level instructions in natural language, and it figures out how to break the work down, spawn workers, and coordinate results.

### From the terminal

```bash
# Send a one-liner — the lead decides how to execute it
team "review all open PRs, fix any failing checks, and merge them"

# Or attach and have a back-and-forth conversation
team attach
```

### From Claude Code

If you have the `/team` skill installed in Claude Code, you can delegate directly from your editor:

```
/team review all open PRs and merge the ones that are ready
/team refactor the auth module and add integration tests
/team bump the version to 0.3.0, update the changelog, and tag a release
```

### What the lead does

When you give the lead a complex task, it will:

1. **Analyze** the request and plan the work
2. **Spawn workers** — one per sub-task, running in parallel tmux windows
3. **Monitor** each worker's progress
4. **Read logs** to check results as workers finish
5. **Handle issues** — spawn follow-up workers if something fails
6. **Report back** with a summary of what was done

You can redirect the lead at any time:

```bash
team "actually skip PR #4, just merge the first three"
team "what's the status on the test fix?"
```

### Example interaction

```
You:    team "review the 3 open PRs and merge them"

Lead:   I'll review all 3 PRs in parallel.
        [spawns worker: review-pr-1]
        [spawns worker: review-pr-2]
        [spawns worker: review-pr-3]
        ...
        PR #1 and #3 look good. PR #2 has a failing test.
        [spawns worker: fix-pr-2-tests]
        ...
        Fix applied. Merging all 3 PRs in order.
        Done — all merged successfully.
```

## Check progress

While the lead works, you can monitor from another terminal:

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

For batch execution with predefined tasks, you can also use task files:

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
