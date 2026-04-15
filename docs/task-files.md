# Task Files

Task files are parsed by `src/agentic_team/taskfile.py`. This page documents the format that code accepts today.

## What the parser recognizes

There are only two structural elements:

1. `## ...` headings, which set the current working-directory context
2. checkbox list items, which become tasks

Minimal example:

```markdown
## ~/repos/backend
- [ ] Fix the login bug
- [ ] Add regression tests (provider: codex, mode: oneshot)

## ~/repos/frontend
- [x] Landing page already done
- [ ] Refresh the hero copy (name: hero-copy)
```

Parser rules:

- A task line must look like `- [ ] ...` or `- [x] ...`.
- Checked items (`- [x]`) are parsed, but `team run` ignores them because it only acts on unchecked tasks.
- The parser preserves indentation and writes status annotations back onto the same line.
- A `##` heading applies to every later task until another `##` heading appears.
- Only a leading `~` is expanded in headings. Other relative paths are kept as written.

## Valid inline keys

Inline overrides must appear at the end of the task line inside one trailing `(key: value, key: value)` block.

```markdown
- [ ] Add tests (provider: codex, mode: oneshot, model: o3)
```

Supported keys:

| Key | Meaning |
|-----|---------|
| `provider` | Provider override for this task |
| `mode` | Worker mode override: `interactive` or `oneshot` |
| `model` | Model override for this task |
| `name` | Explicit worker name |
| `working_dir` | Per-task working directory override |
| `dir` | Alias for `working_dir` |

Important details:

- Unknown keys are ignored by the parser.
- Overrides are stripped from `TaskEntry.task` internally, but the original line text stays in the file and is preserved on writeback.
- Task matching later prefers the `← worker-name` annotation. If that annotation is missing, `team run` falls back to exact task-text matching.

## Before and after writeback

Before `team run`:

```markdown
## ~/repos/backend
- [ ] Fix login expiry handling (name: fix-expiry)
- [ ] Add a regression test (provider: codex, mode: oneshot, model: o3)
```

After `team run tasks.md`:

```markdown
## ~/repos/backend
- [ ] Fix login expiry handling (name: fix-expiry) ← fix-expiry | running
- [ ] Add a regression test (provider: codex, mode: oneshot, model: o3) ← add-regression | running
```

After `team sync tasks.md` once both workers finish:

```markdown
## ~/repos/backend
- [x] Fix login expiry handling (name: fix-expiry) ← fix-expiry | done | 4m 12s
- [x] Add a regression test (provider: codex, mode: oneshot, model: o3) ← add-regression | done | 1m 08s
```

The annotation format is:

```text
← <worker-name> | <worker-status> | <elapsed>
```

`elapsed` is omitted until `team sync` has a value to write.

## Running a task file

```bash
team run tasks.md
team run tasks.md --dry-run
team run tasks.md --limit 3
```

What `team run` does:

1. Refresh current worker status first.
2. Read only unchecked tasks.
3. Match each task to an existing worker by annotation first, then by exact task text.
4. Skip tasks whose matched worker is still `running`.
5. Skip tasks whose matched worker is `done`, unless `--rerun` is set.
6. Spawn or rerun up to the available slot count.

Available slots are calculated as:

```text
(--limit or team.max_workers) - currently running workers
```

## `team sync`

```bash
team sync tasks.md
```

`team sync` only updates lines that already have a `← worker-name` annotation. It:

- copies current worker status into the annotation
- writes elapsed time
- changes `[ ]` to `[x]` when the worker status is `done`

If a task line has never been annotated, `team sync` leaves it alone.

## Cookbook

### Mixed-provider batch

Use per-task overrides to mix providers, models, modes, and directories in one file:

```markdown
## ~/repos/app
- [ ] Review the API change list (provider: claude, name: api-review)
- [ ] Reproduce the flaky test (provider: codex, mode: interactive, name: codex-flake)
- [ ] Draft release notes (provider: gemini, mode: oneshot, name: release-notes)
- [ ] Update docs screenshots (dir: ~/repos/docs-site, provider: claude, model: sonnet)
```

The team defaults still apply to any key you do not override.

### `--rerun` with an interactive worker

If a completed task maps to an existing interactive worker, `team run --rerun` does not spawn a new window. It sends the task text back into that same worker pane and marks the worker `running` again.

Use this when you want the same interactive session to keep iterating on a task:

```bash
team run tasks.md --rerun
```

### `--rerun` with a Claude oneshot worker

If a completed worker has a stored Claude `session_id`, rerun uses a resume command instead of a fresh command. That preserves provider-side context for oneshot follow-ups.

This automatic path depends on the saved worker having:

- `mode == oneshot`
- `provider == claude`
- a captured `session_id`

If any of those are missing, rerun falls back to a fresh worker command in the same tmux window.

### `--rerun` with other oneshot workers

For Codex, and for Gemini workers without a stored session ID, rerun sends a fresh provider command into the existing worker window. It does not create a new worker name unless the task no longer matches the old one.

### Seed a worker from an existing provider session

You can bypass task-file matching and start a worker directly from a known provider session ID:

```bash
team spawn-worker --task "continue the release notes" \
  --provider gemini \
  --mode oneshot \
  --name release-notes \
  --resume-session abc123
```

That worker now has a saved `session_id`, so later `team resume release-notes "tighten the summary"` can reuse it.

### Keep task matching stable

If you edit the human-readable task text after the worker is created, keep the `← worker-name` annotation intact. That annotation is the strongest link between file lines and saved worker state.
