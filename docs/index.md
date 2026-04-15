# agentic-team

Orchestrate teams of AI coding agents working in parallel inside tmux sessions.

A **team lead** agent runs interactively and delegates tasks to **worker** agents (Claude, Codex, Gemini) that execute in their own tmux windows. Workers can run in oneshot or interactive mode, each with independent working directories, providers, and models.

```
User ──> team CLI ──> tmux session
                       ├── window 0: Team Lead (interactive)
                       ├── window 1: worker "fix-auth"
                       ├── window 2: worker "add-tests"
                       └── ...
```

## Demo

![agentic-team demo](demo.gif)

## Features

- **Multi-provider**: Supports Claude Code, Codex, and Gemini CLI agents
- **Parallel execution**: Workers run in isolated tmux windows with automatic logging
- **Two worker modes**: Interactive (persistent, supports follow-ups) and oneshot (fire-and-forget)
- **Task files**: Define batch tasks in markdown with checkbox syntax
- **Smart routing**: `team "your prompt"` sends directly to the lead agent
- **Completion detection**: Automatic status tracking via tmux pane analysis
- **Multi-window dashboard**: `team attach --multi` for a tiled view of all workers
- **Session resumption**: Resume completed Claude workers with full context

## Installation

```bash
pip install agentic-team
```

See [Getting Started](getting-started.md) for prerequisites and first-run setup.
