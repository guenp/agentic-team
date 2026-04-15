# Examples

## Multi-provider comparison

![Multi-provider comparison demo](compare-providers.gif)

Run the same task across different providers to compare how each approaches it.

### Task file

Create `compare-providers.md`:

```markdown
# Provider Comparison — Quick demo

## .
- [ ] List all Python files in src/ and count total lines of code. (provider: claude, name: claude-loc)
- [ ] List all Python files in src/ and count total lines of code. (provider: codex, name: codex-loc)
```

### Run it

```bash
# Initialize with Claude as the team lead
team init compare --provider claude

# Spawn workers from the task file
team run compare-providers.md

# Watch progress
team status

# Compare output
team logs claude-loc
team logs codex-loc
```

### Scaling up

For a more thorough comparison (e.g. a security audit across all three providers), see `demo/compare-providers-audit.md`:

```bash
team run demo/compare-providers-audit.md

# After all workers finish, ask the lead to synthesize:
team "Review the output from all workers with 'team logs'. Compare the findings \
and write a consolidated report."
```

---

## Code review with multiple reviewers

Assign the same PR or diff to multiple agents for independent reviews, then have the lead merge the feedback.

### Task file

Create `multi-review.md`:

```markdown
# Code Review — PR #42

## ~/repos/myproject
- [ ] Review the changes in PR #42 (run 'gh pr diff 42'). Focus on correctness and edge cases. List any bugs. (provider: claude, name: review-correctness)
- [ ] Review the changes in PR #42 (run 'gh pr diff 42'). Focus on code style, naming, and readability. Suggest improvements. (provider: codex, name: review-style)
- [ ] Review the changes in PR #42 (run 'gh pr diff 42'). Focus on performance and security. Flag any concerns. (provider: gemini, name: review-security)
```

```bash
team init review --provider claude --working-dir ~/repos/myproject
team run multi-review.md

# After all are done:
team "All reviewers are done. Compile the feedback from 'team logs review-correctness', \
'team logs review-style', and 'team logs review-security' into a single review \
comment. Post it to PR #42 using 'gh pr comment 42 --body <comment>'."
```

---

## Parallel test investigation

When a CI run has multiple test failures, assign each failure to a separate worker:

### Task file

Create `fix-tests.md`:

```markdown
# Fix failing tests

## ~/repos/backend
- [ ] Fix the failing test in tests/test_auth.py::test_login_expired_token. Run the test to confirm. (name: fix-expired-token)
- [ ] Fix the failing test in tests/test_api.py::test_rate_limiting. Run the test to confirm. (name: fix-rate-limit)
- [ ] Fix the failing test in tests/test_db.py::test_migration_rollback. Run the test to confirm. (name: fix-rollback)
```

```bash
team init fixci --provider claude --working-dir ~/repos/backend
team run fix-tests.md

# Monitor until all are done
team status

# Have the lead verify nothing else broke
team "All test fixes are in. Run the full test suite with 'pytest' and report \
if anything else broke. If all green, commit the fixes."
```

---

## Multi-window dashboard

Monitor all workers at once with a tiled tmux view:

```bash
team init myproject --provider claude --working-dir ~/repos/myproject
team run tasks.md

# Open a tiled dashboard showing all workers side by side
team attach --multi
```

Each pane is a real interactive tmux pane — you can scroll, resize, and interact with workers directly. Running `team attach --multi` again re-attaches without modifying the layout.

Use `Ctrl-b d` to detach. Run `team attach` to switch back to individual tabs.

---

## Interactive lead session

The most hands-on way to use agentic-team is to attach to the lead's tmux window and talk to it directly. The lead runs Claude Code, so you can use slash commands and natural language interchangeably.

### Setup

```bash
# Start a team
team init myproject --provider claude --working-dir ~/repos/myproject

# Attach to the lead's session
team attach
```

You're now inside the lead's Claude Code session.

### Using `/team` inside the lead session

The lead has a `/team` skill that maps your requests to `team` CLI commands. Use it like this:

```
# Run tasks from a file
/team run demo/tasks.md

# Check on workers
/team status

# View a worker's output
/team logs fix-auth

# Send a follow-up to a worker
/team send fix-auth "also handle token refresh"

# Spawn a worker manually
/team spawn --task "Add tests for src/auth.py" --name add-tests

# Resume a completed worker
/team resume fix-auth "now refactor what you wrote"
```

When you say `/team run <file>`, the lead will:

1. Run `team run <file>` to spawn workers from the task file
2. Poll `team status` periodically until all workers finish
3. Review output with `team logs` for each worker
4. Summarize results back to you

### Freeform delegation

You can also give the lead a high-level goal and let it break down the work:

```
/team I need to add OAuth2 login support. One worker should handle the backend
(routes, token validation), one should handle the frontend (login button,
callback page), and one should write tests.
```

The lead will autonomously:

1. Spawn workers with descriptive names and self-contained prompts
2. Poll `team status` to track progress
3. Review output with `team logs`
4. Send follow-ups if a worker needs correction
5. Report back when everything is complete

### Detaching and reattaching

Use `Ctrl-b d` to detach from the tmux session at any time. Workers keep running in the background. Reattach with:

```bash
team attach              # back to lead
team attach -w fix-auth  # jump to a specific worker
```
