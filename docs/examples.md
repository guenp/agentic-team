# Examples

## Multi-provider comparison

![Multi-provider comparison demo](compare-providers.gif)

Run the same task across Claude, Codex, and Gemini to compare how each provider approaches it. A Claude team lead coordinates and reviews the results.

### Task file

Create `compare-providers.md`:

```markdown
# Provider Comparison — Security audit

## ~/repos/myproject
- [ ] Audit the codebase for security issues: command injection in subprocess calls, path traversal in file operations, and unsafe deserialization. Report findings with file paths and line numbers. (provider: claude, name: claude-audit)
- [ ] Audit the codebase for security issues: command injection in subprocess calls, path traversal in file operations, and unsafe deserialization. Report findings with file paths and line numbers. (provider: codex, name: codex-audit)
- [ ] Audit the codebase for security issues: command injection in subprocess calls, path traversal in file operations, and unsafe deserialization. Report findings with file paths and line numbers. (provider: gemini, name: gemini-audit)
```

### Run it

```bash
# Initialize with Claude as the team lead
team init compare --provider claude --working-dir ~/repos/myproject

# Spawn all three workers
team run compare-providers.md

# Watch progress
team status

# Compare output side by side
team logs claude-audit
team logs codex-audit
team logs gemini-audit
```

### Ask the lead to compare

Once all workers are done, ask the team lead to synthesize:

```bash
team "All three workers are done. Review their output with 'team logs claude-audit', \
'team logs codex-audit', and 'team logs gemini-audit'. Compare the findings — \
which audit was most thorough? Were there findings unique to one provider? \
Write a consolidated security report to audit-report.md."
```

### What to expect

Each provider has different strengths:

- **Claude** tends to produce thorough implementations with detailed explanations and considers edge cases
- **Codex** is fast and produces concise, functional code with minimal commentary
- **Gemini** often provides alternative approaches and explains trade-offs

The team lead reviews all three outputs and writes a comparison report, giving you a structured way to evaluate different AI approaches to the same problem.

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

## Interactive lead session

Instead of task files, let the team lead handle everything. Just give it a high-level goal:

```bash
team init build --provider claude --working-dir ~/repos/myproject

team "I need to add OAuth2 login support. Break this into subtasks and spawn \
workers for each. Use interactive mode so you can send follow-ups if needed. \
One worker should handle the backend (routes, token validation), one should \
handle the frontend (login button, callback page), and one should write tests. \
Use 'team status' to monitor and 'team logs <name>' to review output."
```

The lead will autonomously:

1. Spawn three workers with descriptive names
2. Poll `team status` to track progress
3. Review output with `team logs`
4. Send follow-ups if a worker needs correction
5. Report back when everything is complete
