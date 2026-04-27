# Test Plan for agentic-team

## Overview

This plan covers comprehensive testing of the `agentic-team` CLI without spawning real agents or requiring a running tmux server. The core constraint: **real agent invocations cost tokens/money and real tmux requires a terminal**. All tests must run in CI with no external dependencies.

The strategy builds on the existing `FakeTmux` pattern (already used in `test_robustness.py` and `test_efficiency.py`) and extends it into a shared fixture. Agent CLI commands are tested by **asserting the exact command strings we construct**, not by running them. Status detection is tested by **feeding sample pane output** through the parsing functions.

### What we test
- Command construction (exact flags, arguments, quoting)
- Tmux command dispatch (what subprocess args would be sent)
- Status detection (pattern matching against sample agent outputs)
- State management (TOML persistence, config lifecycle, rollback)
- Task file parsing and writeback
- CLI command routing and option handling
- Name generation and deduplication
- Error handling and recovery

### What we do NOT test
- Actual agent intelligence or output quality
- Real tmux session behavior (rendering, pane layout pixel positions)
- Real provider authentication flows (network calls to Anthropic/OpenAI/Google)
- Rich/TUI rendering fidelity (visual formatting is tested by running the tool)

---

## File Structure

```
tests/
  conftest.py                    # Shared FakeTmux, fixtures, temp dir helpers
  test_efficiency.py             # (existing) snapshot caching, streaming
  test_robustness.py             # (existing) error recovery, rollback
  test_names.py                  # Name generation from tasks
  test_config.py                 # TeamConfig, WorkerState, TOML round-trip
  test_taskfile.py               # Markdown task file parsing and writeback
  test_models.py                 # Provider registry, flag generation, health checks
  test_agents.py                 # Command building (lead, worker, resume)
  test_status.py                 # Status detection, pattern matching, state transitions
  test_tmux.py                   # TmuxOrchestrator command dispatch (RecordingTmux)
  test_cli_init.py               # `team init` command flows
  test_cli_spawn.py              # `team spawn-worker` command flows
  test_cli_run.py                # `team run` / `team sync` task file flows
  test_cli_commands.py           # send, status, wait, logs, attach, stop, clear, etc.
  test_cli_routing.py            # TeamGroup routing, typo detection, --team flag
  samples/                       # Sample pane output fixtures
    claude_oneshot_done.txt
    claude_oneshot_error.txt
    claude_interactive_idle.txt
    claude_interactive_working.txt
    claude_waiting_approval.txt
    codex_interactive_idle.txt
    codex_interactive_working.txt
    codex_waiting_confirm.txt
    gemini_interactive_idle.txt
    gemini_interactive_working.txt
    gemini_waiting_confirm.txt
    claude_session_id.txt
```

**Estimated totals: 13 test files, ~120-150 individual test cases.**

---

## Stubbing / Mocking Architecture

### 1. Shared `FakeTmux` (in `conftest.py`)

Consolidate the two existing `FakeTmux` classes into a single shared implementation. The existing pattern is good — extend it with a few capabilities:

```python
class FakeTmux:
    """Drop-in replacement for TmuxOrchestrator in tests.

    Constructed with canned state:
    - windows: list of TmuxWindow (what list-windows returns)
    - pane_output: dict[target_name, str] (what capture-pane returns)
    - dead_targets: set of targets whose panes have exited
    - delivered: list of worker names whose prompts were delivered
    - session_alive: bool (whether has-session succeeds)

    Also records calls for assertion:
    - sent_keys: list[(target, text)] — every send_keys call
    - killed_windows: list[str] — every kill_window call
    - spawned_workers: list[dict] — every spawn_worker call args
    - created_sessions: list[dict] — every create_session call args
    """
```

Key properties:
- **No subprocess calls**: Every method returns canned data or records the call
- **Configurable per-test**: Constructor accepts the exact state the test needs
- **Call recording**: Tests can assert what tmux operations *would have* happened
- **Snapshot-compatible**: Returns proper `TmuxSnapshot` objects so status.py works unchanged

### 2. `RecordingTmux` (in `conftest.py`)

For tests that need to verify the exact tmux subprocess commands dispatched (already in `test_efficiency.py`). This subclasses `TmuxOrchestrator` and overrides `_run()` to record args and return canned `CompletedProcess` results. Used for:
- Verifying exact tmux command arguments (session creation flags, window options)
- Testing snapshot caching (call counting)
- Testing `_resolve_target` in multi-pane mode

### 3. Config isolation fixture

A pytest fixture (or `setUp` helper) that:
- Creates a temp directory
- Patches `config.BASE_DIR`, `config.TEAMS_DIR`, `config.STATE_DIR`, `config.LOGS_DIR`, `config.ACTIVE_LINK`
- Patches `status.STATE_DIR`
- Provides a fake `workdir` path
- Cleans up on teardown

This is already done manually in `test_robustness.py`; promote it to a shared fixture.

### 4. No `FakeAgent` needed

We do NOT need a fake agent process. The agent CLI is never called directly in tests because:
- **Command construction** is tested by asserting the string output of `build_worker_command()`, `build_lead_command()`, `build_resume_command()`
- **Agent output parsing** is tested by feeding sample pane text into `_is_oneshot_done()`, `_is_interactive_idle()`, `_is_waiting_for_input()`, `_extract_exit_code()`
- **CLI flows** use `FakeTmux` which returns canned pane output — the agent never runs

### 5. Provider health mocking

For CLI tests that check provider readiness, mock `get_provider_health()` and `_resolve_provider_choice()` to return a canned `ProviderHealth` object:

```python
FAKE_HEALTH = ProviderHealth(
    name="claude", cli_command="claude",
    installed=True, authenticated=True,
    cli_path="/usr/bin/claude", detail="ok",
)
```

---

## Test Cases by Module

### `test_names.py` — Name Generation (~10 tests)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_name_from_simple_task` | `name_from_task("Fix the login bug", [])` → `"fix-login"` |
| 2 | `test_name_strips_stop_words` | `name_from_task("Add the new feature to the API", [])` → `"new-feature"` or similar meaningful slug |
| 3 | `test_name_deduplicates` | `name_from_task("fix auth", ["fix-auth"])` → `"fix-auth-2"` |
| 4 | `test_name_deduplicates_chain` | Third duplicate → `"fix-auth-3"` |
| 5 | `test_name_fallback_on_all_stop_words` | `name_from_task("do it", [])` → first NATO fallback `"alpha"` |
| 6 | `test_name_fallback_skips_used` | `name_from_task("do it", ["alpha"])` → `"bravo"` |
| 7 | `test_next_fallback_exhaustion` | All 26 NATO names used → raises `RuntimeError` |
| 8 | `test_match_name_prefix` | `match_name("fix", ["fix-auth", "add-tests"])` → `"fix-auth"` |
| 9 | `test_match_name_no_match` | `match_name("zz", ["fix-auth"])` → `None` |
| 10 | `test_match_name_case_insensitive` | `match_name("FIX", ["fix-auth"])` → `"fix-auth"` |

### `test_config.py` — Configuration & State (~18 tests)

**TeamConfig dataclass:**
| # | Test | Asserts |
|---|------|---------|
| 1 | `test_team_config_defaults` | Default `worker_mode="interactive"`, `permissions="auto"`, `max_workers=6` |
| 2 | `test_team_config_tmux_session` | `TeamConfig(name="demo", ...).tmux_session` → `"team-demo"` |
| 3 | `test_team_config_created_at_auto` | `created_at` is set automatically on construction |

**WorkerState dataclass:**
| # | Test | Asserts |
|---|------|---------|
| 4 | `test_worker_state_defaults` | Default `status="running"`, `source="cli"`, `tmux_window` equals `name` |
| 5 | `test_worker_state_started_at_auto` | `started_at` is set on construction |

**TOML round-trip:**
| # | Test | Asserts |
|---|------|---------|
| 6 | `test_save_load_team_roundtrip` | Save then load returns equivalent `TeamConfig` |
| 7 | `test_save_load_workers_roundtrip` | Save then load returns equivalent `WorkerState` list |
| 8 | `test_load_workers_empty_file` | Empty team → returns `[]` |
| 9 | `test_load_team_not_found` | Raises `FileNotFoundError` |
| 10 | `test_load_workers_invalid_toml` | Already tested; keep for regression |
| 11 | `test_save_workers_strips_none` | Fields with `None` (e.g., `session_id`) are not in TOML output |

**Active team management:**
| # | Test | Asserts |
|---|------|---------|
| 12 | `test_set_and_get_active_team` | `set_active_team("demo")` → `get_active_team_name()` returns `"demo"` |
| 13 | `test_no_active_team` | No symlink → `get_active_team_name()` returns `None` |
| 14 | `test_clear_active_team` | After clear, `get_active_team_name()` returns `None` |
| 15 | `test_get_active_team_raises` | No active team → `get_active_team()` raises `RuntimeError` |

**Logging directories:**
| # | Test | Asserts |
|---|------|---------|
| 16 | `test_create_session_log_dir` | Creates timestamped dir and "current" symlink |
| 17 | `test_current_session_log_dir` | Returns resolved path of "current" symlink |
| 18 | `test_atomic_write_creates_parents` | Writing to nested path creates parent dirs |

### `test_taskfile.py` — Task File Parsing (~16 tests)

**Parsing:**
| # | Test | Asserts |
|---|------|---------|
| 1 | `test_parse_unchecked_task` | `- [ ] Fix bug` → `TaskEntry(task="Fix bug", done=False)` |
| 2 | `test_parse_checked_task` | `- [x] Fix bug` → `TaskEntry(done=True)` |
| 3 | `test_parse_heading_sets_workdir` | `## ~/repos/backend` sets `working_dir` for subsequent tasks |
| 4 | `test_parse_tilde_expansion` | `~/repos` is expanded to absolute path |
| 5 | `test_parse_inline_overrides` | `(provider: codex, mode: interactive)` → `provider="codex"`, `mode="interactive"` |
| 6 | `test_parse_model_override` | `(model: o4-mini)` → `model="o4-mini"` |
| 7 | `test_parse_name_override` | `(name: my-worker)` → `name="my-worker"` |
| 8 | `test_parse_strips_annotation` | `Fix bug ← worker-1 \| done \| 2m` → `task="Fix bug"` (annotation stripped) |
| 9 | `test_parse_extracts_worker_name_from_annotation` | `← worker-1` → `worker_name="worker-1"` |
| 10 | `test_parse_mixed_file` | File with headings, checked/unchecked, overrides, annotations → correct list |
| 11 | `test_parse_preserves_line_numbers` | `line_number` matches 0-indexed position |
| 12 | `test_parse_preserves_indent` | Indented tasks preserve indent string |
| 13 | `test_pending_tasks_filters` | `pending_tasks()` returns only `done=False` entries |
| 14 | `test_parse_missing_file_raises` | Nonexistent path → `TaskFileError` |

**Writeback:**
| # | Test | Asserts |
|---|------|---------|
| 15 | `test_update_ticks_checkbox` | `- [ ]` becomes `- [x]` when `entry.done=True` |
| 16 | `test_update_appends_annotation` | Annotation `← worker-1 \| done \| 2m 30s` appended; old annotation replaced |

### `test_models.py` — Provider Registry & Flags (~14 tests)

**Provider lookup:**
| # | Test | Asserts |
|---|------|---------|
| 1 | `test_get_provider_known` | `get_provider("claude")` returns `ProviderConfig` with `cli_command="claude"` |
| 2 | `test_get_provider_unknown` | `get_provider("unknown")` → `KeyError` with available providers listed |
| 3 | `test_all_providers_have_ready_indicators` | Every provider in `PROVIDERS` has at least one `ready_indicators` entry |

**Flag generation (`describe_provider_flags`):**
| # | Test | Asserts |
|---|------|---------|
| 4 | `test_claude_interactive_flags` | `["--permission-mode", "auto"]` (no oneshot args) |
| 5 | `test_claude_oneshot_flags` | `["--print", "--output-format", "stream-json", "--permission-mode", "auto"]` |
| 6 | `test_claude_with_model` | `["--model", "opus", "--permission-mode", "auto"]` |
| 7 | `test_codex_interactive_flags` | `["--full-auto"]` (no permission-mode) |
| 8 | `test_codex_oneshot_flags` | `["--full-auto", "--quiet"]` |
| 9 | `test_gemini_interactive_flags` | `["--yolo"]` |
| 10 | `test_gemini_oneshot_flags` | `["--yolo", "--prompt"]` |

**Provider health (mocked subprocess):**
| # | Test | Asserts |
|---|------|---------|
| 11 | `test_health_not_installed` | `shutil.which` returns None → `installed=False`, `viable=False` |
| 12 | `test_claude_auth_success` | Mock `claude auth status` returns JSON `{loggedIn: true}` → `authenticated=True` |
| 13 | `test_claude_auth_failure` | JSON `{loggedIn: false}` → `authenticated=False` |
| 14 | `test_gemini_auth_env_var` | `GEMINI_API_KEY` set → `authenticated=True` |

### `test_agents.py` — Command Construction (~16 tests)

This is the **agent CLI compatibility** layer. These tests are the contract between agentic-team and each provider CLI. If a provider CLI changes its flags, these tests break first.

**Lead command:**
| # | Test | Asserts |
|---|------|---------|
| 1 | `test_build_lead_claude` | Command starts with `claude`, includes `--append-system-prompt-file`, `--verbose`, `--permission-mode auto`, stderr redirect `2>>` |
| 2 | `test_build_lead_codex` | Command starts with `codex`, includes `--full-auto`, has `RUST_LOG=info` env prefix |
| 3 | `test_build_lead_gemini` | Command starts with `gemini`, includes `--yolo`, `--debug` |

**Worker command (interactive):**
| # | Test | Asserts |
|---|------|---------|
| 4 | `test_build_worker_claude_interactive` | `claude --permission-mode auto --append-system-prompt "You are a worker..." --verbose 2>> /path/to/log` |
| 5 | `test_build_worker_codex_interactive` | `RUST_LOG=info RUST_LOG_FORMAT=json codex --full-auto 2>> /path/to/log` |
| 6 | `test_build_worker_gemini_interactive` | `gemini --yolo --debug 2>> /path/to/log` |

**Worker command (oneshot):**
| # | Test | Asserts |
|---|------|---------|
| 7 | `test_build_worker_claude_oneshot` | Includes `--print --output-format stream-json`, task as positional arg, stdout+stderr redirect `> /path 2>&1` |
| 8 | `test_build_worker_codex_oneshot` | `codex --full-auto --quiet "task text"` with `> /path 2>&1` |
| 9 | `test_build_worker_gemini_oneshot` | `gemini --yolo --prompt "task text"` with `> /path 2>&1` |

**Worker command with model override:**
| # | Test | Asserts |
|---|------|---------|
| 10 | `test_build_worker_with_model` | `--model opus` appears in command |

**Resume command:**
| # | Test | Asserts |
|---|------|---------|
| 11 | `test_build_resume_claude_oneshot` | `claude --print --output-format stream-json --resume <session-id> "prompt"` |
| 12 | `test_build_resume_claude_interactive` | `claude --resume <session-id>` (no positional prompt) |
| 13 | `test_build_resume_gemini` | `gemini --yolo --resume <session-id>` |
| 14 | `test_build_resume_codex_raises` | Codex has no `resume_flag` → `ValueError` |

**System prompt generation:**
| # | Test | Asserts |
|---|------|---------|
| 15 | `test_worker_system_prompt_contains_team_and_dir` | Includes team name and working directory |
| 16 | `test_lead_system_prompt_contains_commands` | Includes `spawn-worker`, `status`, `wait`, `max_workers` value |

### `test_status.py` — Status Detection & Pattern Matching (~28 tests)

This is the largest and most critical test file — it validates the heuristics that detect whether agents are done, idle, working, or waiting.

**Exit code extraction:**
| # | Test | Asserts |
|---|------|---------|
| 1 | `test_extract_exit_code_zero` | `"__AGENTIC_TEAM_EXIT__=0"` → `0` |
| 2 | `test_extract_exit_code_nonzero` | `"__AGENTIC_TEAM_EXIT__=127"` → `127` |
| 3 | `test_extract_exit_code_multiple` | Last sentinel wins |
| 4 | `test_extract_exit_code_none` | No sentinel → `None` |
| 5 | `test_extract_exit_code_empty` | Empty/None input → `None` |

**Error description:**
| # | Test | Asserts |
|---|------|---------|
| 6 | `test_describe_exit_command_not_found` | Exit 127 + "command not found" → `"agent command not found on PATH"` |
| 7 | `test_describe_exit_generic_error` | Exit 1 + last line with "error" → returns that line |
| 8 | `test_describe_exit_interactive` | Interactive mode exit → includes last content line |

**Oneshot completion detection (`_is_oneshot_done`):**
| # | Test | Asserts |
|---|------|---------|
| 9 | `test_oneshot_done_json_result` | Pane shows `"type":"result"` after `claude --print` command → `True` |
| 10 | `test_oneshot_done_exit_sentinel` | Pane shows `__AGENTIC_TEAM_EXIT__=0` after command → `True` |
| 11 | `test_oneshot_done_shell_prompt` | Shell prompt (`$`, `%`, `❯`) after command output → `True` |
| 12 | `test_oneshot_not_done_still_running` | No completion signal, command visible → `False` |
| 13 | `test_oneshot_not_done_no_command` | No agent command visible in pane → `False` |
| 14 | `test_oneshot_done_ignores_old_output` | Previous run's shell prompt present, but LAST command has no completion → `False` |

**Interactive idle detection (`_is_interactive_idle`):**
| # | Test | Asserts |
|---|------|---------|
| 15 | `test_claude_idle_no_esc_to_interrupt` | No "esc to inter" + >5 content lines → `True` |
| 16 | `test_claude_working_esc_to_interrupt` | "esc to inter" in tail → `False` |
| 17 | `test_claude_startup_not_idle` | <5 content lines → `False` |
| 18 | `test_codex_idle_worked_for` | "Worked for 30 seconds" in output → `True` |
| 19 | `test_codex_idle_prompt` | "›" in last 5 lines, no "Working (" → `True` |
| 20 | `test_codex_working` | "Working (" in output → `False` |
| 21 | `test_gemini_idle` | "Type your message" + >10 content lines → `True` |
| 22 | `test_gemini_working` | No "Type your message" → `False` |

**Waiting-for-input detection (`_is_waiting_for_input`):**
| # | Test | Asserts |
|---|------|---------|
| 23 | `test_claude_waiting_approval` | "(Y/n)" in tail, no "esc to inter" → `True` |
| 24 | `test_claude_not_waiting_while_working` | "esc to inter" visible → `False` |
| 25 | `test_codex_waiting_confirm` | "Would you like to run" in tail → `True` |
| 26 | `test_gemini_waiting` | "[Y/n]" in tail → `True` |

**Session ID extraction:**
| # | Test | Asserts |
|---|------|---------|
| 27 | `test_extract_session_id_from_json` | Pane with `"session_id":"<uuid>"` after claude command → `worker.session_id` set |
| 28 | `test_extract_session_id_wrapped_lines` | UUID split across pane lines → still extracted |

**Full `get_team_status` integration (with FakeTmux):**

These tests are partially covered in existing files. Additional cases:
| # | Test | Asserts |
|---|------|---------|
| 29 | `test_status_oneshot_done_marks_done` | Oneshot worker with shell prompt → status `"done"` |
| 30 | `test_status_interactive_idle_marks_done` | Interactive idle worker → status `"done"` |
| 31 | `test_status_waiting_marks_waiting` | Worker showing approval prompt → status `"waiting"` |
| 32 | `test_status_window_disappeared` | Worker not in windows → status `"error"`, message mentions disappeared |
| 33 | `test_status_pane_dead` | Worker pane dead → status `"error"` |
| 34 | `test_status_done_interactive_revives` | Done interactive worker with non-dead pane and non-idle output → back to `"running"` |
| 35 | `test_status_multi_mode_joined` | Worker in `multi_targets` but not in windows → NOT marked as error |

### `test_tmux.py` — TmuxOrchestrator Command Dispatch (~12 tests)

Uses `RecordingTmux` (subclass with `_run` override) to verify exact subprocess args.

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_create_session_command` | Dispatches `tmux new-session -d -s team-demo -n lead -c /path -x 220 -y 50` |
| 2 | `test_create_session_sets_options` | Sends `set-option allow-rename off` and `set-option window-size smallest` |
| 3 | `test_create_window_command` | `tmux new-window -t team-demo -n worker-1 -c /path` |
| 4 | `test_send_keys_literal` | `tmux send-keys -t team-demo:lead -l "text"` then `tmux send-keys ... Enter` |
| 5 | `test_send_shell_command_wraps_exit` | Command wrapped with `; echo __AGENTIC_TEAM_EXIT__=$?` |
| 6 | `test_capture_pane_command` | `tmux capture-pane -t team-demo:worker -p -S -50` |
| 7 | `test_list_windows_format` | `tmux list-windows -t team-demo -F ...` with correct format string |
| 8 | `test_kill_window_command` | `tmux kill-window -t team-demo:worker` |
| 9 | `test_kill_session_command` | `tmux kill-session -t team-demo` |
| 10 | `test_resolve_target_multi_mode` | With multi_targets file → translates `"bob"` to `"host.2"` |
| 11 | `test_snapshot_caching` | Already tested; keep for regression |
| 12 | `test_capture_pane_safe_retries` | Returns `None` after retries on failure (no crash) |

### `test_cli_init.py` — Init Command (~8 tests)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_init_creates_config_and_workers` | After init: team config TOML exists, workers.toml exists (empty), active link points to team |
| 2 | `test_init_creates_session_log_dir` | Timestamped log dir created, "current" symlink set |
| 3 | `test_init_rollback_on_tmux_failure` | Already tested; keep for regression (no leftover config, workers, active link, logs) |
| 4 | `test_init_rejects_running_team` | Team with live session → error "already running" |
| 5 | `test_init_overwrites_stale_config` | Team config exists but no session → overwrites |
| 6 | `test_init_auto_detects_provider` | Single viable provider → selected without `--provider` |
| 7 | `test_init_rejects_no_providers` | No viable providers → error listing all |
| 8 | `test_init_rejects_multiple_providers` | Multiple viable → error "pass --provider explicitly" |

### `test_cli_spawn.py` — Spawn Worker Command (~10 tests)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_spawn_creates_worker_state` | After spawn: worker appears in `load_workers()` with correct fields |
| 2 | `test_spawn_generates_name` | No `--name` → name derived from task |
| 3 | `test_spawn_uses_custom_name` | `--name my-worker` → `worker.name == "my-worker"` |
| 4 | `test_spawn_rejects_duplicate_name` | Name already in use → error |
| 5 | `test_spawn_rejects_max_workers` | At limit → error "max workers reached" |
| 6 | `test_spawn_rollback_on_failure` | Already tested; keep for regression |
| 7 | `test_spawn_interactive_sends_prompt` | FakeTmux records `send_keys` with task text |
| 8 | `test_spawn_oneshot_bakes_prompt` | Command string contains task as positional arg |
| 9 | `test_spawn_inherits_team_defaults` | No `--mode`, `--provider`, `--model` → uses team config values |
| 10 | `test_spawn_overrides_team_defaults` | Explicit `--provider codex` overrides team's `claude` |

### `test_cli_run.py` — Task File Run & Sync (~10 tests)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_run_spawns_unchecked_tasks` | 3 unchecked tasks → 3 workers spawned |
| 2 | `test_run_skips_checked_tasks` | Checked tasks not spawned |
| 3 | `test_run_respects_limit` | `--limit 2` → only 2 spawned |
| 4 | `test_run_dry_run` | `--dry-run` → prints plan, spawns nothing |
| 5 | `test_run_uses_task_overrides` | `(provider: codex)` in task → worker uses codex |
| 6 | `test_run_uses_heading_workdir` | Task under `## ~/repos/backend` → worker working_dir set |
| 7 | `test_run_rerun_reruns_done_workers` | `--rerun` + done worker → new session spawned |
| 8 | `test_run_skips_running_workers` | Task with running annotation → skipped |
| 9 | `test_sync_ticks_done_tasks` | Done worker → `- [x]` in file |
| 10 | `test_sync_updates_annotations` | Status annotation updated: `← worker-1 \| done \| 2m 30s` |

### `test_cli_commands.py` — Other CLI Commands (~12 tests)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_send_dispatches_to_lead` | `team send "hello"` → FakeTmux records `send_keys("lead", "hello")` |
| 2 | `test_send_fails_no_session` | No session → error |
| 3 | `test_status_prints_table` | Output contains worker names, statuses |
| 4 | `test_logs_reads_log_file` | Log file exists → contents printed |
| 5 | `test_logs_falls_back_to_capture` | No log file → uses `capture_pane` |
| 6 | `test_logs_partial_name_match` | `team logs fix` matches `fix-auth` |
| 7 | `test_stop_worker_kills_window` | FakeTmux records `kill_window` call; worker marked done |
| 8 | `test_clear_removes_done_workers` | Done workers removed from state; windows killed |
| 9 | `test_stop_kills_session` | `team stop` → session killed; active link cleared |
| 10 | `test_list_shows_teams` | Multiple teams → output lists each with provider and running/stopped |
| 11 | `test_doctor_all_pass` | tmux + provider + lead all healthy → output shows all checks |
| 12 | `test_resume_sends_to_interactive` | Interactive worker → `send_keys` with follow-up message |

### `test_cli_routing.py` — TeamGroup Routing (~5 tests)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_bare_prompt_routes_to_send` | `team "hello world"` → invokes `send` |
| 2 | `test_typo_suggests_command` | `team statsu` → "Did you mean 'status'?" |
| 3 | `test_unknown_not_typo_routes_to_send` | `team "completely unrelated text"` → routes to `send` |
| 4 | `test_team_flag_selects_team` | `team -T other status` → operates on "other" team |
| 5 | `test_team_flag_not_found` | `team -T nonexistent status` → error |

---

## Agent CLI Compatibility Strategy

The agent CLIs (Claude, Codex, Gemini) are external tools that can change flags at any time. Our strategy has three layers:

### Layer 1: Command string snapshot tests (in `test_agents.py`)

Every `build_*_command()` function has tests that assert the **exact command string** produced. When a provider CLI changes flags, updating the `ProviderConfig` in `models.py` will break these tests, forcing us to review the change.

Example: if Claude CLI renames `--append-system-prompt` to `--system-prompt`, the `test_build_worker_claude_interactive` test fails.

### Layer 2: Output pattern tests (in `test_status.py`)

The `samples/` directory contains representative pane output from each provider. Tests feed these samples through the detection functions. When providers change their output format (e.g., Codex changes "Worked for" to "Completed in"), we update the sample and the detection heuristic together.

**How to capture samples:** Run a real agent once, `tmux capture-pane -p > samples/claude_interactive_idle.txt`. These are committed to the repo as fixtures.

### Layer 3: Optional live smoke test (CI flag)

A lightweight integration test behind a flag (`TEAM_LIVE_SMOKE=1 pytest tests/test_smoke.py`) that:
1. Starts a real tmux session
2. Runs `claude --print "echo hello"` (minimal token cost)
3. Verifies `_is_oneshot_done()` detects completion
4. Tears down the session

This runs only in scheduled CI (weekly) or manually, not on every PR. It catches drift in provider CLI behavior that snapshot tests can't detect.

**Not included in the initial test file list** — this is a future enhancement once the unit/integration layer is solid.

---

## Sample Pane Output Fixtures

The `samples/` directory contains real (or realistic) captures of what `tmux capture-pane` returns for each provider in each state. These are the test inputs for status detection.

Example `claude_oneshot_done.txt`:
```
$ claude --print --output-format stream-json --append-system-prompt 'You are a worker...' 'Fix the login bug'
{"type":"assistant","message":{"content":"I'll fix the login bug..."}}
{"type":"result","subtype":"success","session_id":"abc-123-def"}
__AGENTIC_TEAM_EXIT__=0
$
```

Example `codex_interactive_idle.txt`:
```
OpenAI Codex

Use /skills to see what I can do

› Fix the login bug

Working (2.3s)
Worked for 12 seconds

›
```

Each sample is loaded by tests and fed to the relevant detection function. When providers update their output format, we update these samples.

---

## Implementation Priority

1. **`conftest.py`** — Shared fixtures (FakeTmux, config isolation). Unblocks everything.
2. **`test_names.py`** — Pure functions, zero mocking needed. Quick win.
3. **`test_config.py`** — State management correctness. Foundation for CLI tests.
4. **`test_taskfile.py`** — Pure parsing, easy to test, important for `run`/`sync`.
5. **`test_models.py`** — Provider registry, flag contract.
6. **`test_agents.py`** — Command construction contract. Critical for CLI compatibility.
7. **`test_status.py`** + `samples/` — Status detection heuristics. Most complex, highest value.
8. **`test_tmux.py`** — Command dispatch verification.
9. **`test_cli_*.py`** — Full CLI flows. Depends on all of the above.
10. **`test_cli_routing.py`** — TeamGroup behavior. Low effort, good regression guard.
