<p align="center">
  <img src="https://guen.pw/agentic-team/logo.png" alt="agentic-team" width="280">
</p>

<p align="center">
  Orchestrate teams of AI coding agents working in parallel inside tmux sessions.
</p>

A **team lead** agent runs interactively and delegates tasks to **worker** agents (Claude, Codex, Gemini) in separate tmux windows. Workers can run in `interactive` or `oneshot` mode, with per-worker provider, model, and working-directory overrides.

```text
User ──> team CLI ──> tmux session
                       ├── window 0: lead
                       ├── window 1: fix-auth
                       ├── window 2: add-tests
                       └── ...
```

## Demo

![agentic-team demo](https://guen.pw/agentic-team/demo.gif)

## Installation

Requires Python 3.11+ and [tmux](https://github.com/tmux/tmux).

```bash
pip install agentic-team
```

Or install from source with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/guenp/agentic-team.git
cd agentic-team
uv sync
```

You also need at least one provider CLI installed and already authenticated:

- `claude`
- `codex`
- `gemini`

`agentic-team` does not install or log in those CLIs for you. See [docs/providers.md](docs/providers.md) for the exact flags, resume support, system-prompt behavior, permission handling, and provider-specific caveats.

## 5-minute first run

1. Install `tmux` and `agentic-team`.
2. Install one provider CLI from its official docs.
3. Authenticate that provider.
4. Verify the environment with `team doctor`.
5. Start the team.

```bash
# tmux is required
brew install tmux
# or: sudo apt install tmux

# install one provider CLI
# Claude Code: https://docs.anthropic.com/en/docs/claude-code
# Codex CLI:   https://github.com/openai/codex
# Gemini CLI:  https://github.com/google-gemini/gemini-cli

# authenticate the provider you plan to use
claude auth login
# or: codex login
# Gemini: configure GEMINI_API_KEY / GOOGLE_API_KEY, or complete Gemini CLI auth

# verify tmux + provider install/auth
team doctor --provider claude

# if exactly one provider is installed and authenticated, team init auto-detects it
team init myproject --working-dir ~/repos/myproject
# otherwise pass --provider claude|codex|gemini
```

## Quick start

```bash
# Initialize a team (provider auto-detected when only one is viable)
team init myproject --working-dir ~/repos/myproject
# or choose explicitly
team init myproject --provider claude --working-dir ~/repos/myproject

# Send a task to the lead
team "fix the auth bug and add tests for the login flow"

# Inspect progress
team status
team logs

# Attach to the tmux session
team attach
```

The lead agent receives a generated team-lead prompt when the provider supports system-prompt injection. Today that means Claude; Codex and Gemini leads run with provider-specific CLI flags only.

## How to use it: talk to the lead

The primary workflow is **conversational delegation** — you talk to the lead agent like a project manager, and it breaks down work, spawns workers, monitors progress, and synthesizes results.

### Starting a session

From your terminal:

```bash
team init myproject --provider claude --working-dir ~/repos/myproject
```

Or from inside Claude Code, use the `/team` skill:

```
/team start a new team for ~/repos/myproject
```

Either way you get a lead agent running in a tmux session, ready to take instructions.

### Delegating work with natural language

Once the lead is running, send it tasks in plain English. The lead decides how many workers to spawn, what each one does, and coordinates the results.

```bash
# One-liner delegation
team "review all open PRs, fix any issues, and merge them"

# Or attach and chat interactively
team attach
```

From Claude Code:

```
/team review all open PRs and merge the ones that are ready
```

The lead will:

1. **Analyze** the request and break it into discrete tasks
2. **Spawn workers** — one per PR, one per bug fix, etc.
3. **Monitor** each worker's progress via `team status`
4. **Read logs** to check worker output when they finish
5. **Synthesize** results and report back to you

### Example: reviewing and merging PRs

Here is a realistic interaction showing the conversational flow:

```
You:    /team review all 4 open PRs, fix any issues, and merge them in order

Lead:   I'll spawn 4 workers to review the PRs in parallel.
        [spawns worker: review-pr-1]
        [spawns worker: review-pr-2]
        [spawns worker: review-pr-3]
        [spawns worker: review-pr-4]

Lead:   All 4 reviews are done. PRs #1 and #3 are clean.
        PR #2 has a failing test — spawning a worker to fix it.
        PR #4 has a merge conflict — spawning a worker to resolve it.
        [spawns worker: fix-pr-2]
        [spawns worker: fix-pr-4]

Lead:   Fixes are in. Merging in order: #1, #2, #3, #4.
        All 4 PRs merged successfully. Here's the summary:
        - PR #1: Added auth middleware — merged cleanly
        - PR #2: Fixed login bug (test fix applied) — merged
        - PR #3: Updated docs — merged cleanly
        - PR #4: Refactored config (conflict resolved) — merged
```

You stay in control — you can redirect the lead at any time:

```
You:    skip PR #4 for now, just merge the first three
You:    also tag a release after merging
You:    what's the status on the test fix for PR #2?
```

### Example: multi-step release workflow

```
You:    /team run the full release process — review PRs, merge them,
        bump the version, update the changelog, and tag a release

Lead:   Starting with PR review. I see 3 open PRs.
        [spawns 3 review workers]
        ...
        All PRs reviewed and merged.
        Now bumping version to v0.3.0 and updating CHANGELOG.md.
        [spawns worker: bump-version]
        ...
        Version bumped. Creating git tag v0.3.0 and pushing.
        Release complete. Summary: ...
```

### Checking on progress

While the lead is working, you can check status from another terminal:

```bash
team status          # table of all workers and their states
team logs            # recent output from all workers
team standup         # ask the lead for a markdown summary
team attach --multi  # tiled tmux view of all workers
```

## Command quick reference

Global options:

```text
team [--version] [-T TEAM] COMMAND [ARGS]...
TEAM_NAME=<team> team COMMAND [ARGS]...
```

`-T/--team` and `TEAM_NAME` select a specific team instead of the active team.

### Team lifecycle

```bash
# Verify tmux, provider auth, and the active lead session
team doctor [--provider claude|codex|gemini]

# Initialize a new team
team init NAME [-p claude|codex|gemini] [-m MODEL]
               [--worker-mode oneshot|interactive]
               [--permissions auto|default|dangerously-skip-permissions]
               [--max-workers INTEGER] [-C DIRECTORY]

team list
team stop [NAME]
```

### Lead interaction

```bash
team "PROMPT..."
team send PROMPT...
team attach [-w WINDOW] [-m]
team standup [--timeout INTEGER] [-v]
```

### Worker management

```bash
team spawn-worker -t TASK [--mode oneshot|interactive]
                  [--provider claude|codex|gemini] [--model MODEL]
                  [-n NAME] [-C DIRECTORY] [-r SESSION_ID]

team status [WORKER_NAME] [-v]
team logs [WORKER_NAME] [-n TAIL] [-a]
team send-to-worker WORKER_NAME MESSAGE...
team resume WORKER_NAME PROMPT...
team stop-worker WORKER_NAME
team wait [-t TIMEOUT] [-i INTERVAL]
team clear
```

### Task files

```bash
team run TASK_FILE [-l LIMIT] [--dry-run] [--rerun]
team sync TASK_FILE
```

The full command reference is in [docs/commands.md](docs/commands.md).

## Task files

Task files are markdown checklists. Headings set a working-directory context, and trailing `(key: value)` overrides customize individual tasks.

```markdown
## ~/repos/backend
- [ ] Fix the login bug
- [ ] Add regression tests (provider: codex, mode: oneshot)
- [ ] Update docs screenshots (dir: ~/repos/docs-site, name: docs-shots)
```

```bash
team run tasks.md
team sync tasks.md
team run tasks.md --rerun
```

Supported inline keys today are:

- `provider`
- `mode`
- `model`
- `name`
- `working_dir`
- `dir`

The full parser and writeback rules are in [docs/task-files.md](docs/task-files.md).

## Managing multiple teams

```bash
team list
team -T other-team status
TEAM_NAME=other-team team logs lead
```

`team init` makes the new team active. `-T` and `TEAM_NAME` let you inspect another team without changing the active symlink. Full details are in [docs/multiple-teams.md](docs/multiple-teams.md).

## How it works

1. `team init` saves a team config, creates `~/.agentic-team/logs/<team>/<timestamp>/`, and starts the lead in tmux session `team-<name>`.
2. `team spawn-worker` or `team run` builds provider-specific commands from [`src/agentic_team/models.py`](src/agentic_team/models.py) and [`src/agentic_team/agents.py`](src/agentic_team/agents.py).
3. New interactive workers receive their first prompt only after `capture-pane` shows a ready screen; that queued prompt lives under `~/.agentic-team/state/<team>/pending_prompts/`.
4. `team status` refreshes worker state by checking tmux panes, provider-specific idle signals, and Claude oneshot session IDs.
5. `team logs` reads the current session log file first, then falls back to tmux pane capture when the file is empty or unavailable.

## Runtime layout

```text
~/.agentic-team/
├── teams/
│   └── myproject.toml
├── state/
│   └── myproject/
│       ├── workers.toml
│       ├── pending_prompts/
│       ├── multi_targets
│       └── standup.md
├── logs/
│   └── myproject/
│       ├── 20260415-003621/
│       │   ├── lead.log
│       │   ├── fix-auth.log
│       │   └── add-tests.log
│       └── current -> 20260415-003621
└── active -> state/myproject
```

## Further reading

- [docs/getting-started.md](docs/getting-started.md)
- [docs/providers.md](docs/providers.md)
- [docs/multiple-teams.md](docs/multiple-teams.md)
- [docs/commands.md](docs/commands.md)
- [docs/task-files.md](docs/task-files.md)
- [docs/examples.md](docs/examples.md)
- [docs/operations.md](docs/operations.md)
- [docs/architecture.md](docs/architecture.md)
- [demo/lead-workflow.md](demo/lead-workflow.md) — full walkthrough of the interactive lead workflow

## License

MIT
