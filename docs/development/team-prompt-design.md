# Design: `team prompt` — Re-inject the lead system prompt

## Problem

After running `team init`, the lead agent receives its system prompt once via `--append-system-prompt-file`. As the conversation grows, the lead may drift from its coordinator role — spawning fewer workers, writing code itself, or forgetting available commands. There is no way to remind it of its instructions without restarting the session.

The user wants to run `/team prompt` (via the skill) or `team prompt` (via CLI) and have the lead's original system prompt re-sent into the active session.

## Current state

1. `team init` calls `agents.write_system_prompt_file(team)` which writes `TEAM_LEAD_SYSTEM_PROMPT` (formatted with team name, max workers, working dir) to a tempfile.
2. The tempfile path is passed to `claude --append-system-prompt-file <path>`.
3. Claude Code reads the file at startup. The file is cleaned up on rollback but otherwise left on disk (no explicit delete on success).
4. The prompt is **not persisted** anywhere in `~/.agentic-team/` — there is no record of what was sent to the lead after init.
5. `team send` delivers text to the lead pane via `tmux send-keys`. The lead sees it as a user message, not a system prompt.

## Design

### What `team prompt` does

`team prompt` re-sends the team lead system prompt into the active lead session as a user-visible message. It is not a true system prompt re-injection (Claude Code does not support changing the system prompt mid-session) — it is a "reminder" delivered as a regular message.

### CLI surface

```
team prompt [OPTIONS]
```

| Option | Meaning |
|--------|---------|
| `--dry-run` | Print the prompt to stdout instead of sending it |
| `--custom FILE` | Send a custom prompt file instead of the default |

No arguments needed — the command reconstructs the prompt from the active team's config.

### Skill mapping

| User says | Effect |
|-----------|--------|
| `/team prompt` | Runs `team prompt` — re-sends the lead system prompt |
| `/team prompt --dry-run` | Prints the prompt so the user can review it |

### Implementation

#### 1. New CLI command (`cli.py`)

```python
@app.command()
@click.option("--dry-run", is_flag=True, help="Print the prompt instead of sending it.")
@click.option("--custom", type=click.Path(exists=True), help="Custom prompt file to send.")
def prompt(dry_run: bool, custom: str | None) -> None:
    """Re-send the team lead system prompt to the active lead session."""
    team = _get_team()

    if custom:
        text = Path(custom).read_text()
    else:
        text = agents.build_team_lead_system_prompt(team)

    if dry_run:
        click.echo(text)
        return

    tmux = _ensure_lead_started(team)
    preamble = (
        "SYSTEM PROMPT REMINDER — The following is your original system prompt. "
        "Re-read it carefully and follow these instructions for the rest of this session."
    )
    tmux.send_keys("lead", f"{preamble}\n\n{text}")
    click.echo("Lead system prompt re-sent.")
```

Key points:
- The prompt is **reconstructed** from the current `TeamConfig`, not cached from init. This means if the user changed `max_workers` or `working_dir` since init, the re-sent prompt reflects the current config.
- The preamble tells the lead to treat this as an authoritative instruction, not a user question to answer.

#### 2. Persist the prompt at init time (optional enhancement)

Save the rendered prompt alongside the team config so there is a durable record:

```
~/.agentic-team/state/<team>/lead-prompt.txt
```

`team prompt` would read from this file if it exists, falling back to `build_team_lead_system_prompt(team)`. This captures any future init-time customizations (e.g. user-supplied prompt fragments) that wouldn't be reproducible from config alone.

This is not required for v1 since the prompt is currently a pure function of `TeamConfig`.

#### 3. Update the `/team` skill (`skills/team.md`)

Add to the command mapping table:

```
| `/team prompt` | `team prompt` (re-send lead system prompt) |
```

### Message framing

The lead receives this as a regular user message, not a system prompt. To maximize compliance:

1. **Preamble** — a short header that signals this is an instruction refresh, not a user task.
2. **Full prompt body** — the exact `TEAM_LEAD_SYSTEM_PROMPT` text, formatted with current config values.
3. **No trailing question** — the message ends with the prompt, not "what do you think?" The lead should acknowledge and continue.

The preamble matters because without it, the lead may interpret the prompt text as something the user wants it to _analyze_ rather than _follow_.

### Alternatives considered

**A. Use `--resume` with a fresh system prompt** — Claude Code's `--resume` does not accept `--append-system-prompt-file`, so this path is blocked.

**B. Kill and restart the lead session** — This works (`team stop && team init`) but loses all conversation context. `team prompt` is specifically for when you want to keep the context but reset the behavioral instructions.

**C. Persist the prompt as a file and `cat` it into the pane** — Similar to the chosen approach but uses `cat` + pipe instead of `send-keys`. No advantage and harder to control timing.

**D. Automatic periodic re-injection** — Send the prompt every N messages automatically. Over-engineered for now; the user can run `/team prompt` when they notice drift. Could be added later as `team prompt --auto-interval N`.

### Scope

v1:
- [x] `team prompt` CLI command
- [x] `--dry-run` flag
- [x] `--custom` flag for user-supplied prompts
- [x] Skill mapping in `skills/team.md`

Future:
- [ ] Persist rendered prompt at init time (`state/<team>/lead-prompt.txt`)
- [ ] `team prompt --edit` — open the prompt in `$EDITOR` before sending
- [ ] Support for user prompt fragments (e.g. `~/.agentic-team/lead-prompt.md` appended to the system prompt)
- [ ] `team prompt --auto-interval N` — periodic re-injection
