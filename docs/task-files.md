# Task Files

Task files let you define batch work in markdown with checkbox syntax. Each unchecked item becomes a worker.

## Format

```markdown
## ~/repos/backend
- [ ] Fix the login bug
- [ ] Add tests for the auth module (provider: codex, mode: oneshot)

## ~/repos/frontend
- [ ] Update the landing page (name: landing)
```

### Headings as working directories

`##` headings set the working directory for all tasks that follow. Paths are resolved relative to the user's home directory. Tasks without a heading use the team's default working directory.

### Inline overrides

Add `(key: value)` at the end of a task line to override defaults:

| Key | Values | Description |
|-----|--------|-------------|
| `provider` | `claude`, `codex`, `gemini` | Agent provider for this task |
| `mode` | `oneshot`, `interactive` | Worker mode |
| `model` | any model name | Model override |
| `name` | any string | Custom worker name |

Multiple overrides can be combined: `(provider: codex, mode: oneshot)`.

## Running tasks

```bash
# Spawn workers for all unchecked tasks
team run tasks.md

# Preview without spawning
team run tasks.md --dry-run

# Limit how many tasks to spawn
team run tasks.md --limit 3
```

## Annotations

After spawning, `team run` annotates each task line with the assigned worker:

```markdown
- [ ] Fix the login bug ← adder | running
```

On subsequent runs, already-assigned tasks are skipped unless `--rerun` is used.

## Syncing status

After workers complete, update the task file:

```bash
team sync tasks.md
```

This ticks off completed tasks and updates annotations:

```markdown
- [x] Fix the login bug ← adder | done | 3m 42s
- [ ] Add tests for the auth module ← bear | running
```

## Re-running tasks

Use `--rerun` to re-execute tasks that have already completed:

```bash
team run tasks.md --rerun
```

For interactive workers, this sends the task text to the existing session. For oneshot workers with a captured session ID, it resumes with full context.
