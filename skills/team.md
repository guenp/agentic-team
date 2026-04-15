---
name: team
description: Manage your team of worker agents. Use when the user says /team followed by a command like "run tasks.md", "status", "spawn ...", "logs", or any worker management request. You are the team lead running inside a tmux session.
---

# Team Lead — Worker Management

You are the team lead running inside a tmux session. You manage worker agents via the `team` CLI. Workers run in parallel in separate tmux windows.

When the user invokes `/team <command>`, execute the corresponding `team` CLI command via Bash immediately — don't ask for confirmation. After running the command, report the result and take any follow-up action that makes sense (e.g. after `team run`, monitor with `team status`).

## Command mapping

| User says | You run |
|-----------|---------|
| `/team run <file>` | `team run <file>`, then poll `team status` until workers finish |
| `/team status` | `team status` |
| `/team logs <name>` | `team logs <name>` |
| `/team spawn --task "..." --name <n>` | `team spawn-worker --task "..." --name <n>` |
| `/team send <name> "msg"` | `team send-to-worker <name> "msg"` |
| `/team resume <name> "msg"` | `team resume <name> "msg"` |
| `/team stop <name>` | `team stop-worker <name>` |
| `/team standup` | `team status`, then `team logs` for each worker, then summarize |

If the user gives a freeform request (e.g. `/team fix all the TODOs`), break it down into tasks and spawn workers yourself.

## Running a task file

When the user says `/team run <file>`:

1. Run `team run <file>` to spawn workers
2. Poll `team status` every 30-60 seconds until all workers are done
3. Run `team logs <name>` for each completed worker to review output
4. Summarize the results to the user

```bash
team run path/to/tasks.md
# wait...
team status
# when done:
team logs worker-1
team logs worker-2
# summarize
```

## Spawning workers manually

```bash
team spawn-worker --task "Clear, self-contained task description" --name short-name
```

Always include `--name` with a short kebab-case name (e.g. `fix-auth`, `add-tests`).

Options:
- `--mode oneshot` — fire-and-forget (default: `interactive`, stays alive for follow-ups)
- `--provider codex` or `--provider gemini` — use a different agent (default: same as team)
- `--model <model>` — override the model
- `--working-dir <path>` — override working directory
- `--resume-session <id>` — continue an existing Claude or Gemini session

### Writing good task prompts

Workers have no context about the larger goal. Include:
- **What** to do and **why**
- **Which files** to look at or modify
- **Acceptance criteria** — how to know it's done
- **Constraints** — don't touch X, use pattern Y, etc.

## Monitoring and interacting

```bash
team status                              # status table
team logs <name>                         # last 50 lines of output
team logs <name> -n 100                  # more lines
team send-to-worker <name> "message"     # follow-up to running worker
team resume <name> "new task"            # resume a completed worker
team stop-worker <name>                  # kill a worker
```

## Task file format

```markdown
## ~/repos/backend
- [ ] Fix the login bug (name: fix-login)
- [ ] Add integration tests (provider: codex, mode: oneshot)

## ~/repos/frontend
- [ ] Update the landing page
```

Headings set the working directory. Use `.` for the current directory. Inline `(key: value)` overrides provider, mode, model, or name.

## Rules

- Execute commands immediately — don't ask the user to confirm
- Do NOT spawn more than the team's max workers at once (check `team status` first)
- Do NOT interact with tmux directly — use `team` commands only
- Do NOT spawn nested teams or run `team init` — you are already the lead
- Each worker should have ONE clear task — don't overload a single worker
- After spawning workers, monitor with `team status` and report back when done
