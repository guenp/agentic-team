# Examples

These examples use only behavior that exists in the current CLI and task-file parser.

## Mixed-provider batch

Run a small batch where each task uses a different provider or mode.

### Task file

```markdown
## ~/repos/myproject
- [ ] Review the current auth flow and list risky edge cases. (provider: claude, name: auth-review)
- [ ] Reproduce the flaky login test and describe the failure mode. (provider: codex, mode: interactive, name: codex-flake)
- [ ] Draft a short release-note entry for the auth fix. (provider: gemini, mode: oneshot, name: auth-notes)
```

### Run it

```bash
team init review --provider claude --working-dir ~/repos/myproject
team run tasks.md
team status
team logs auth-review
team logs codex-flake
team logs auth-notes
```

Why this works:

- each task overrides provider and mode independently
- worker names stay stable because the file sets `name: ...`
- `team logs` can compare the outputs side by side after completion

## Rerun completed tasks from the same file

Use this when a worker finished but you want one more pass without creating a new worker name.

### First pass

```markdown
## ~/repos/backend
- [ ] Fix token refresh expiry handling (name: fix-refresh)
- [ ] Add regression tests for refresh expiry (provider: claude, mode: oneshot, name: refresh-tests)
```

```bash
team init backend --provider claude --working-dir ~/repos/backend
team run tasks.md
team sync tasks.md
```

### Rerun

Leave the items unchecked or uncheck them again, then:

```bash
team run tasks.md --rerun
```

What happens:

- `fix-refresh` reuses the same interactive worker window and receives the task text again
- `refresh-tests` reuses the same worker window and resumes the Claude oneshot session if a `session_id` was captured

## Seed a worker from an existing session

If you already have a Claude or Gemini session ID from outside the current team, start a worker from that session directly.

```bash
team init docs --provider gemini --working-dir ~/repos/docs
team spawn-worker \
  --task "continue the migration checklist" \
  --provider gemini \
  --mode oneshot \
  --name migration-checklist \
  --resume-session abc123
```

Follow it up later:

```bash
team resume migration-checklist "tighten the acceptance criteria section"
```

## Inspect the lead and produce a standup

Use this after a batch has been running for a while.

```bash
team logs lead
team status lead -v
team standup --timeout 180
```

This gives you three different views of the same lead session:

- `team logs lead` for recent captured output
- `team status lead -v` for a live pane tail
- `team standup` for a markdown report written to `state/<team>/standup.md`

## Compare providers on the same task

This is the simplest way to do side-by-side provider evaluation.

```markdown
## .
- [ ] Count all Python files under src/ and summarize the code layout. (provider: claude, name: claude-loc)
- [ ] Count all Python files under src/ and summarize the code layout. (provider: codex, name: codex-loc)
- [ ] Count all Python files under src/ and summarize the code layout. (provider: gemini, name: gemini-loc)
```

```bash
team init compare --provider claude
team run compare-providers.md
team wait
team logs claude-loc
team logs codex-loc
team logs gemini-loc
```

If you want the lead to synthesize the results:

```bash
team "Read team logs for claude-loc, codex-loc, and gemini-loc. Summarize the differences."
```
