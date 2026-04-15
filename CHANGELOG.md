# Changelog

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
