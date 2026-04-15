# Lead Workflow Demo Script

This script shows a realistic interactive session with `agentic-team`. It demonstrates the primary workflow: talking to the lead agent like a project manager to review PRs, fix issues, merge in order, and cut a release.

This can be used as a reference for recording a demo gif or as a walkthrough for new users.

---

## Scenario

You have a project with 4 open pull requests. You want to:

1. Review all 4 PRs in parallel
2. Fix any issues found during review
3. Merge PRs in the correct order
4. Tag a release

## Session transcript

### 1. Start the team

From your terminal:

```bash
team init myproject --provider claude --working-dir ~/repos/myproject
```

Or from Claude Code:

```
/team start a team for ~/repos/myproject
```

Output:

```
✓ Team "myproject" initialized
  Provider: claude
  Working dir: ~/repos/myproject
  Session: team-myproject
  Lead is ready.
```

### 2. Delegate the PR review

```bash
team "Review all 4 open PRs in this repo. For each one, check code quality,
test coverage, and whether CI passes. Report back with a summary."
```

The lead analyzes the request and spawns workers:

```
Lead:   I'll review all 4 open PRs in parallel. Spawning workers now.

        [spawns worker: review-pr-1 — "Review PR #1: Add auth middleware"]
        [spawns worker: review-pr-2 — "Review PR #2: Fix login bug"]
        [spawns worker: review-pr-3 — "Review PR #3: Update documentation"]
        [spawns worker: review-pr-4 — "Review PR #4: Refactor config loading"]
```

### 3. Check progress while workers run

In another terminal:

```bash
team status
```

```
Team: myproject (claude)

  Worker          Status     Mode         Task
  ──────────────  ─────────  ───────────  ──────────────────────────────
  lead            active     interactive  —
  review-pr-1     active     interactive  Review PR #1: Add auth middleware
  review-pr-2     active     interactive  Review PR #2: Fix login bug
  review-pr-3     done       interactive  Review PR #3: Update documentation
  review-pr-4     active     interactive  Review PR #4: Refactor config loading
```

Or watch all workers live:

```bash
team attach --multi
```

### 4. Lead reports review results

After all 4 workers finish, the lead reads their logs and synthesizes:

```
Lead:   All 4 PR reviews are complete. Here's the summary:

        PR #1 (Add auth middleware) — APPROVED
          Clean code, good test coverage, CI green.

        PR #2 (Fix login bug) — NEEDS FIX
          The fix works but test_login_refresh is failing.
          The test expects a 200 but the endpoint now returns 201.

        PR #3 (Update documentation) — APPROVED
          Docs look accurate. No code changes.

        PR #4 (Refactor config loading) — NEEDS FIX
          Has a merge conflict with main in config/settings.py.

        Should I fix the issues in PR #2 and #4 before merging?
```

### 5. Direct the lead to fix issues

```bash
team "Yes, fix both issues. Update the test assertion in PR #2 and resolve
the merge conflict in PR #4. Then merge all 4 in order: #1, #3, #2, #4."
```

The lead spawns fix workers:

```
Lead:   On it. Spawning workers to fix both PRs.

        [spawns worker: fix-pr-2 — "Fix failing test assertion in PR #2"]
        [spawns worker: fix-pr-4 — "Resolve merge conflict in PR #4"]
```

### 6. Monitor the fixes

```bash
team status
```

```
  Worker          Status     Mode         Task
  ──────────────  ─────────  ───────────  ──────────────────────────────
  lead            active     interactive  —
  review-pr-1     done       interactive  Review PR #1: Add auth middleware
  review-pr-2     done       interactive  Review PR #2: Fix login bug
  review-pr-3     done       interactive  Review PR #3: Update documentation
  review-pr-4     done       interactive  Review PR #4: Refactor config loading
  fix-pr-2        active     interactive  Fix failing test assertion in PR #2
  fix-pr-4        done       interactive  Resolve merge conflict in PR #4
```

```bash
team logs fix-pr-4
```

```
[fix-pr-4] Resolved conflict in config/settings.py — kept both
           the new loader and the refactored structure. Pushed.
           CI is green.
```

### 7. Lead merges PRs in order

Once both fixes are done, the lead proceeds:

```
Lead:   Both fixes are in and CI is passing. Merging in order now.

        ✓ PR #1 (Add auth middleware) — merged
        ✓ PR #3 (Update documentation) — merged
        ✓ PR #2 (Fix login bug) — merged (with test fix)
        ✓ PR #4 (Refactor config loading) — merged (conflict resolved)

        All 4 PRs merged successfully.
```

### 8. Ask the lead to cut a release

```bash
team "Great. Now bump the version to v0.3.0, update the CHANGELOG
with entries for all 4 PRs, and create a git tag."
```

```
Lead:   I'll handle the release process.

        [spawns worker: release — "Bump to v0.3.0, update CHANGELOG, tag"]

        ...

        Done. Release v0.3.0 is tagged and ready.
        - Version bumped in pyproject.toml
        - CHANGELOG.md updated with 4 entries
        - Git tag v0.3.0 created

        Want me to push the tag and create a GitHub release?
```

### 9. Wrap up

```bash
team "Yes, push the tag and create the release."
```

```
Lead:   Tag pushed. GitHub release v0.3.0 created with the changelog
        entries as the release body.

        Summary of this session:
        - Reviewed 4 PRs in parallel (2 min)
        - Fixed issues in 2 PRs (1 min)
        - Merged all 4 PRs in order
        - Released v0.3.0

        All done!
```

Check the final status:

```bash
team status
```

```
  Worker          Status     Mode         Task
  ──────────────  ─────────  ───────────  ──────────────────────────────
  lead            active     interactive  —
  review-pr-1     done       interactive  Review PR #1: Add auth middleware
  review-pr-2     done       interactive  Review PR #2: Fix login bug
  review-pr-3     done       interactive  Review PR #3: Update documentation
  review-pr-4     done       interactive  Review PR #4: Refactor config loading
  fix-pr-2        done       interactive  Fix failing test assertion in PR #2
  fix-pr-4        done       interactive  Resolve merge conflict in PR #4
  release         done       interactive  Bump to v0.3.0, update CHANGELOG, tag
```

Stop the team when you're done:

```bash
team stop
```

---

## Key takeaways

- **You talk, the lead works.** Give high-level instructions; the lead handles task decomposition, worker management, and coordination.
- **Workers run in parallel.** The lead spawns independent workers that execute simultaneously in their own tmux windows.
- **The lead adapts.** When workers find issues, the lead can spawn follow-up workers to fix them without you micromanaging.
- **You stay in control.** Redirect the lead at any point — skip tasks, change order, ask for status, or add new work.
- **Everything is observable.** Use `team status`, `team logs`, and `team attach --multi` to see what's happening at any time.
