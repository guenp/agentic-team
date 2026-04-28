# Changelog

## v0.4.0 (2026-04-28)

### Features

- **User defaults** ([#13](https://github.com/guenp/agentic-team/pull/13), [#22](https://github.com/guenp/agentic-team/pull/22)) — Add `~/.agentic-team/defaults.toml` support for default providers and per-provider model defaults.
- **Team skill routing** — Add folder/project routing to the team skill and lead system prompt.
- **Worktree behavior** — Make git worktree isolation opt-in instead of default.

### Improvements

- **Codex model support** ([#20](https://github.com/guenp/agentic-team/pull/20)) — Add `gpt-5.5` to Codex models and remove the unsupported `--quiet` flag.
- **Worker startup timeout** ([#21](https://github.com/guenp/agentic-team/pull/21)) — Increase the interactive worker ready timeout and expose a per-worker timeout override.

### Bug Fixes

- **CLI version** — Fix `team --version` reporting stale package metadata.
- **Worker cleanup** — Fix `team clear` missing workers that completed but still had stale status.

### Documentation

- Add development notes, a high-level architecture document, and a test plan.

## v0.3.0 (2026-04-15)

### Features

- **Coordinator-only team lead** ([#9](https://github.com/guenp/agentic-team/pull/9)) — Enforce team lead as coordinator-only, never doing implementation work directly.
- **Git worktree isolation** — Implement git worktree isolation for parallel workers, enabling safe concurrent work across branches.

### Tests

- **Comprehensive test suite** ([#8](https://github.com/guenp/agentic-team/pull/8)) — Added 120+ new tests across all modules.

### Documentation

- **Interactive lead workflow** ([#7](https://github.com/guenp/agentic-team/pull/7)) — Document the interactive lead workflow for team orchestration.

### Bug Fixes

- **PyPI project description** ([#6](https://github.com/guenp/agentic-team/pull/6)) — Fix PyPI package page showing no project description.

## v0.2.0 (2026-04-15)

### Highlights

- **Hardened tmux workflows and state persistence** ([#1](https://github.com/guenp/agentic-team/pull/1)) — Introduced `TmuxError` exception hierarchy, atomic state writes, `ExitStack` rollbacks for session cleanup, and `capture_pane_safe` for reliable terminal reads.
- **First-run UX and provider bootstrap checks** ([#2](https://github.com/guenp/agentic-team/pull/2)) — Added the `team doctor` command for health checks, automatic provider detection, and guided setup for new users.
- **Task hot-path efficiency** ([#4](https://github.com/guenp/agentic-team/pull/4)) — `TmuxSnapshot` caching and reduced subprocess calls for faster status polling and task updates.
- **Comprehensive documentation rewrite** ([#3](https://github.com/guenp/agentic-team/pull/3)) — Full mkdocs site with command references, provider guides, architecture docs, and operations guides.

### New Commands

- `team wait` — Block until all workers finish, with live status updates and `q` to quit.
- `team clear` — Remove done workers from status and clean up orphaned tmux windows.
- `team standup` — Summarize worker progress as markdown, with `--verbose` for live streaming.
- `team doctor` — Run provider health checks and diagnose configuration issues.

### Improvements

- Added `waiting` status for workers blocked on confirmation prompts.
- Added `--resume-session` flag to `spawn-worker` for reconnecting to existing sessions.
- Added `--verbose` / `-v` flag to `team status` for live-tail panels with token/budget info.
- Rich table output for `team status` with task source tracking.
- Per-provider idle detection (Claude, Gemini) using `capture_pane` instead of log files.
- Replaced `pipe-pane` logging with native CLI logging for cleaner error messages.
- Disabled tmux automatic window rename to fix false "done" status.
- Rewritten multi-attach using `tmux join-pane`.
- Added `/team` skill for interactive lead use.
- Added `--resume-session` flag to `spawn-worker`.

### Documentation

- Full mkdocs documentation site with commands, providers, architecture, and operations guides.
- Added compare-providers demo gif and quick demo example.
- Updated docs with `team wait`, `team clear`, and `status -v` usage.
- Fixed broken demo gif on examples page.
- Added square 64x64 favicon.

### Bug Fixes

- Fixed false "done" status for interactive workers.
- Fixed idle detection for Claude and Gemini providers.
- Fixed `team status -v` crash when stdin is not a tty.
- Fixed `team clear` to also kill orphaned tmux windows.
- Fixed waiting detection for workers previously marked done.
- Fixed window resize for existing sessions on attach.
- Fall back to `capture-pane` when log files are empty.
