# Getting Started

## Prerequisites

- **Python 3.13+**
- **tmux** -- install via your package manager:

    ```bash
    # macOS
    brew install tmux

    # Ubuntu/Debian
    sudo apt install tmux
    ```

- At least one agent CLI:
    - [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude`)
    - [Codex](https://github.com/openai/codex) (`codex`)
    - [Gemini CLI](https://github.com/google-gemini/gemini-cli) (`gemini`)

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

## Your first team

Initialize a team, specifying the working directory for your project:

```bash
team init myproject --provider claude --working-dir ~/repos/myproject
```

This creates a detached tmux session (`team-myproject`) with a team lead agent running in window 0. The lead receives a system prompt that teaches it how to spawn and manage workers.

Send the lead a task:

```bash
team "fix the auth bug and add tests for the login flow"
```

Or attach to the session to interact directly:

```bash
team attach
```

## Checking progress

```bash
# Status overview
team status

# View worker output
team logs

# View a specific worker
team logs fix-auth

# Tiled dashboard of all workers
team attach --multi
```

## Stopping

```bash
# Stop the team and kill the tmux session
team stop
```
