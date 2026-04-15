# Provider Setup and Behavior

`agentic-team` shells out to provider CLIs. It does not install them, log you in, or normalize their behavior beyond the flags in `src/agentic_team/models.py` and the command builders in `src/agentic_team/agents.py`.

## Before you start

For every provider you plan to use:

1. Install the provider CLI so the expected binary is on `PATH`.
2. Launch that CLI once outside `agentic-team` and complete its own login/auth flow.
3. Verify the binary name matches what `agentic-team` calls: `claude`, `codex`, or `gemini`.

Run `team doctor --provider <name>` to verify that a provider is installed and authenticated before creating a team. The doctor command uses `ProviderHealth` checks that probe the binary path and run a provider-specific auth test.

If a provider CLI is missing or unauthenticated, `team init` and `team spawn-worker` will fail early with install or login hints rather than waiting for tmux to report a confusing error.

## Provider matrix

| Provider | Binary | Install and auth | Lead args | Worker args | Resume support | System prompt support | Permission handling | Logging |
|----------|--------|------------------|-----------|-------------|----------------|-----------------------|--------------------|---------|
| Claude | `claude` | Install Claude Code and sign in before `team init`. | Interactive lead adds `--append-system-prompt-file <tempfile>` and `--verbose`. If `--permissions` is not `default`, it also adds `--permission-mode <mode>`. | Interactive workers add `--append-system-prompt <prompt>` and `--verbose`. Oneshot workers add `--print --output-format stream-json`, `--append-system-prompt <prompt>`, and `--verbose`. | `spawn-worker --resume-session` is supported. Completed oneshot workers can auto-capture `session_id`, so `team resume` and `team run --rerun` can resume them with context. | Yes. Lead uses a temp file; workers use inline text. | `team init --permissions` only affects Claude lead and new worker commands. Resume commands do not re-apply `--permission-mode`. | Interactive commands append stderr to the session log. Oneshot commands write stdout and stderr to the log file. |
| Codex | `codex` | Install Codex CLI and complete its own auth flow before use. | Interactive lead adds `--full-auto`. | Interactive workers add `--full-auto`. Oneshot workers add `--full-auto --quiet`. | No CLI resume support. `--resume-session` is rejected. | No. `agentic-team` does not inject lead or worker system prompts for Codex. | `--permissions` is ignored. No Codex command gets a permission flag. | Sets `RUST_LOG=info` and `RUST_LOG_FORMAT=json`. Interactive commands append stderr to the log; oneshot commands redirect stdout and stderr. |
| Gemini | `gemini` | Install Gemini CLI and complete its own auth flow before use. | Interactive lead adds `--yolo --debug`. | Interactive workers add `--yolo --debug`. Oneshot workers add `--yolo --prompt --debug`. | `spawn-worker --resume-session` is supported. `team resume` also works for oneshot workers that already have a stored session ID. `agentic-team` does not auto-extract Gemini session IDs from completed runs. | No. `agentic-team` does not inject lead or worker system prompts for Gemini. | `--permissions` is ignored. No Gemini command gets a permission flag. | Interactive commands append stderr to the session log. Oneshot commands redirect stdout and stderr to the log file. |

## What the flags mean in practice

### Lead sessions

- Claude gets the richest lead setup: a generated system prompt file, optional permission mode, and verbose stderr logging.
- Codex and Gemini leads only get their provider-specific interactive flags. They do not receive the team-lead system prompt from `agentic-team`.

### Worker sessions

- New interactive workers start the provider CLI first, then receive the task via tmux once the pane looks ready.
- New oneshot workers get the task as part of the command line.
- Resume commands are different from fresh worker commands: they add the provider's resume flag and do not inject a system prompt, model override, or permission flag.

## Resume behavior details

There are three distinct resume paths in the current code:

1. `team spawn-worker --resume-session <id>` starts a new worker from a provider session ID. This is allowed only for providers with a `resume_flag` (`claude` and `gemini`).
2. `team resume <worker> "prompt"` sends text directly to interactive workers, regardless of provider.
3. `team resume` and `team run --rerun` can resume a oneshot worker only when that worker already has a stored `session_id`.

Important caveats:

- Automatic `session_id` extraction exists only for completed Claude oneshot workers.
- Gemini oneshot workers can be resumed only if you seeded them with `--resume-session` earlier; their IDs are not auto-discovered.
- Codex workers always rerun as fresh commands because the provider config has no resume flag.

## Known caveats by provider

### Claude

- Claude is the only provider that receives the built-in lead and worker system prompts.
- Claude oneshot mode uses `stream-json`, and `agentic-team` looks for `"type":"result"` plus `"session_id":"..."` in the captured pane output.
- Resume commands do not preserve `--model`, `--permission-mode`, or system-prompt injection.

### Codex

- Codex workers always run with `--full-auto`.
- The CLI has no resume flag, so `--resume-session` is blocked up front.
- Interactive Codex panes are often more useful than the log file because the TUI rewrites the screen; `team logs` falls back to `capture-pane` when needed.

### Gemini

- Gemini always runs with `--yolo`; oneshot adds `--prompt`.
- Gemini supports manual resume via `--resume`, but the current status code does not harvest Gemini session IDs from finished runs.
- Like Codex, Gemini does not get `agentic-team` system prompts or permission flags.
