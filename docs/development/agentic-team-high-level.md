# agentic-team — High-Level Overview

## Project Overview

agentic-team is a framework for orchestrating teams of AI coding agents (Claude, Codex, Gemini) working in parallel within tmux sessions. A single "lead" agent acts as a coordinator, receiving natural language instructions and delegating tasks to multiple "worker" agents running concurrently in separate tmux windows. The lead can spawn workers on demand, monitor progress, read logs, and synthesize results. Key workflows include conversational delegation, multi-step releases, and bulk PR reviews.

## Source Layout (`src/agentic_team/`)

- **cli.py** — Click CLI entry point; all subcommands
- **config.py** — TOML-based team/worker state management (`~/.agentic-team/`)
- **models.py** — Provider registry (Claude, Codex, Gemini) with provider-specific config and health checks
- **agents.py** — System prompt generation for lead agents and provider-specific command builders
- **tmux.py** — TmuxOrchestrator: centralized tmux session/window/pane management
- **status.py** — Worker status polling and formatting
- **taskfile.py** — Markdown task file parser with inline provider/mode overrides
- **names.py** — Worker name generation utilities

## Key Abstractions

- **ProviderConfig** (`models.py`): Encodes CLI flags, models, and capabilities for each provider (resume, system prompts, output formats)
- **TeamConfig** (`config.py`): Team-level settings (provider, working directory, max workers, permissions mode)
- **WorkerState** (`config.py`): Per-worker metadata (task, status, session ID, worktree path, exit code)
- **TmuxOrchestrator** (`tmux.py`): Handles all tmux operations — creating sessions, spawning windows, capturing output, delivering prompts
- **Lead System Prompt** (`agents.py`): Dynamic instructions injected into the lead agent, listing available `team` commands and emphasizing coordination-only behavior

## Data Flow

The CLI routes high-level commands (`init`, `spawn-worker`, `status`, `logs`, `run`, etc.) through TmuxOrchestrator, which executes provider-specific agent CLIs. Worker state is persisted to `~/.agentic-team/state/<team>/workers.toml`; session logs go to `~/.agentic-team/logs/<team>/<timestamp>/`.

## Tech Stack

- **Language**: Python 3.11+
- **Dependencies**: click (CLI), rich (terminal UI), tomli_w (TOML serialization)
- **Infrastructure**: tmux (session/window management), provider CLIs (claude, codex, gemini)
- **Build**: hatchling, uv for development
- **Storage**: TOML files, text logs
