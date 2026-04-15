"""Tests for status detection, pattern matching, and state transitions.

This is the largest test file — it validates the heuristics that detect
whether agents are done, idle, working, or waiting. Uses sample pane
output fixtures from tests/samples/.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent / "src"))

from agentic_team import config, status
from agentic_team.config import TeamConfig, WorkerState
from agentic_team.tmux import EXIT_SENTINEL, TmuxSnapshot, TmuxWindow

from conftest import FakeTmux, load_sample


# ── Exit code extraction ────────────────────────────────────────


class TestExtractExitCode:
    def test_extract_exit_code_zero(self):
        output = f"some output\n{EXIT_SENTINEL}0\nmore"
        assert status._extract_exit_code(output) == 0

    def test_extract_exit_code_nonzero(self):
        output = f"error output\n{EXIT_SENTINEL}127\n$"
        assert status._extract_exit_code(output) == 127

    def test_extract_exit_code_multiple(self):
        output = f"{EXIT_SENTINEL}1\n{EXIT_SENTINEL}0\n"
        assert status._extract_exit_code(output) == 0  # last wins

    def test_extract_exit_code_none(self):
        output = "some output\nno sentinel here"
        assert status._extract_exit_code(output) is None

    def test_extract_exit_code_empty(self):
        assert status._extract_exit_code(None) is None
        assert status._extract_exit_code("") is None


# ── Error description ───────────────────────────────────────────


class TestDescribeExit:
    def test_describe_exit_command_not_found(self):
        output = "zsh: command not found: claude\n__AGENTIC_TEAM_EXIT__=127"
        result = status._describe_exit(output, 127)
        assert "not found" in result.lower()

    def test_describe_exit_generic_error(self):
        output = "some output\nFatal error: something went wrong"
        result = status._describe_exit(output, 1)
        assert "error" in result.lower()

    def test_describe_exit_interactive(self):
        output = "startup failed\nsome detail line"
        result = status._describe_exit(output, 1, interactive=True)
        assert "some detail line" in result


# ── Oneshot completion detection ────────────────────────────────


class TestOneshotDone:
    def _check(self, pane_output: str, provider: str = "claude") -> bool:
        team = TeamConfig(name="demo", provider=provider)
        worker = WorkerState(
            name="alpha", task="fix bug", provider=provider, mode="oneshot",
        )
        fake_tmux = FakeTmux(
            windows=[TmuxWindow(0, "alpha", 100, False)],
            pane_output={"alpha": pane_output},
        )
        return status._is_oneshot_done(team, worker, fake_tmux)

    def test_oneshot_done_json_result(self):
        output = load_sample("claude_oneshot_done.txt")
        assert self._check(output) is True

    def test_oneshot_done_exit_sentinel(self):
        output = (
            "$ claude --print 'task'\n"
            "some output\n"
            "__AGENTIC_TEAM_EXIT__=0\n"
        )
        assert self._check(output) is True

    def test_oneshot_done_shell_prompt(self):
        output = (
            "$ claude --print 'task'\n"
            "result output here\n"
            "$\n"
        )
        assert self._check(output) is True

    def test_oneshot_not_done_still_running(self):
        output = (
            "$ claude --print 'task'\n"
            "working on it...\n"
        )
        assert self._check(output) is False

    def test_oneshot_not_done_no_command(self):
        output = "some random output\nno agent command visible\n"
        assert self._check(output) is False

    def test_oneshot_done_ignores_old_output(self):
        output = (
            "$ claude --print 'old task'\n"
            "old result\n"
            "$\n"
            "$ claude --print 'new task'\n"
            "still running...\n"
        )
        # The last claude command has no completion signal
        assert self._check(output) is False


# ── Interactive idle detection ──────────────────────────────────


class TestInteractiveIdle:
    def _check(self, pane_output: str, provider: str) -> bool:
        worker = WorkerState(
            name="alpha", task="fix bug", provider=provider, mode="interactive",
        )
        fake_tmux = FakeTmux(
            windows=[TmuxWindow(0, "alpha", 100, False)],
            pane_output={"alpha": pane_output},
        )
        return status._is_interactive_idle(worker, fake_tmux)

    def test_claude_idle_no_esc_to_interrupt(self):
        output = load_sample("claude_interactive_idle.txt")
        assert self._check(output, "claude") is True

    def test_claude_working_esc_to_interrupt(self):
        output = load_sample("claude_interactive_working.txt")
        assert self._check(output, "claude") is False

    def test_claude_startup_not_idle(self):
        # Less than 5 content lines = startup
        output = "Claude Code\n\n/help\n"
        assert self._check(output, "claude") is False

    def test_codex_idle_worked_for(self):
        output = load_sample("codex_interactive_idle.txt")
        assert self._check(output, "codex") is True

    def test_codex_idle_prompt(self):
        output = "OpenAI Codex\n\nUse /skills to see what I can do\n\n\u203a\n"
        assert self._check(output, "codex") is True

    def test_codex_working(self):
        output = load_sample("codex_interactive_working.txt")
        assert self._check(output, "codex") is False

    def test_gemini_idle(self):
        output = load_sample("gemini_interactive_idle.txt")
        assert self._check(output, "gemini") is True

    def test_gemini_working(self):
        output = load_sample("gemini_interactive_working.txt")
        assert self._check(output, "gemini") is False


# ── Waiting-for-input detection ─────────────────────────────────


class TestWaitingForInput:
    def _check(self, pane_output: str, provider: str) -> bool:
        worker = WorkerState(
            name="alpha", task="fix bug", provider=provider, mode="interactive",
        )
        fake_tmux = FakeTmux(
            windows=[TmuxWindow(0, "alpha", 100, False)],
            pane_output={"alpha": pane_output},
        )
        return status._is_waiting_for_input(worker, fake_tmux)

    def test_claude_waiting_approval(self):
        output = load_sample("claude_waiting_approval.txt")
        assert self._check(output, "claude") is True

    def test_claude_not_waiting_while_working(self):
        output = load_sample("claude_interactive_working.txt")
        assert self._check(output, "claude") is False

    def test_codex_waiting_confirm(self):
        output = load_sample("codex_waiting_confirm.txt")
        assert self._check(output, "codex") is True

    def test_gemini_waiting(self):
        output = load_sample("gemini_waiting_confirm.txt")
        assert self._check(output, "gemini") is True


# ── Session ID extraction ───────────────────────────────────────


class TestSessionIdExtraction:
    def test_extract_session_id_from_json(self):
        team = TeamConfig(name="demo", provider="claude")
        worker = WorkerState(
            name="alpha", task="fix bug", provider="claude", mode="oneshot",
        )
        output = load_sample("claude_session_id.txt")
        fake_tmux = FakeTmux(
            windows=[TmuxWindow(0, "alpha", 100, False)],
            pane_output={"alpha": output},
        )
        status._try_extract_session_id(team, worker, tmux=fake_tmux)
        assert worker.session_id == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    def test_extract_session_id_wrapped_lines(self):
        team = TeamConfig(name="demo", provider="claude")
        worker = WorkerState(
            name="alpha", task="fix bug", provider="claude", mode="oneshot",
        )
        # Simulate UUID wrapped across pane lines
        output = (
            '$ claude --print \'task\'\n'
            '{"type":"result","session_id":"a1b2c3d4-e5f6-78\n'
            '90-abcd-ef1234567890"}\n'
            '$\n'
        )
        fake_tmux = FakeTmux(
            windows=[TmuxWindow(0, "alpha", 100, False)],
            pane_output={"alpha": output},
        )
        status._try_extract_session_id(team, worker, tmux=fake_tmux)
        assert worker.session_id == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


# ── Full get_team_status integration ────────────────────────────


class TestGetTeamStatus:
    def test_status_oneshot_done_marks_done(self, isolated_config):
        cfg = isolated_config
        team = TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        worker = WorkerState(
            name="alpha", task="fix bug", provider="claude", mode="oneshot",
        )
        config.save_workers(team.name, [worker])
        output = load_sample("claude_oneshot_done.txt")
        fake_tmux = FakeTmux(
            windows=[TmuxWindow(0, "alpha", 100, False)],
            pane_output={"alpha": output},
        )
        with patch.object(status, "TmuxOrchestrator", return_value=fake_tmux):
            result = status.get_team_status(team)
        assert result["workers"][0]["status"] == "done"

    def test_status_interactive_idle_marks_done(self, isolated_config):
        cfg = isolated_config
        team = TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        worker = WorkerState(
            name="alpha", task="fix bug", provider="claude", mode="interactive",
        )
        config.save_workers(team.name, [worker])
        output = load_sample("claude_interactive_idle.txt")
        fake_tmux = FakeTmux(
            windows=[TmuxWindow(0, "alpha", 100, False)],
            pane_output={"alpha": output},
        )
        with patch.object(status, "TmuxOrchestrator", return_value=fake_tmux):
            result = status.get_team_status(team)
        assert result["workers"][0]["status"] == "done"

    def test_status_waiting_marks_waiting(self, isolated_config):
        cfg = isolated_config
        team = TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        worker = WorkerState(
            name="alpha", task="fix bug", provider="claude", mode="interactive",
        )
        config.save_workers(team.name, [worker])
        output = load_sample("claude_waiting_approval.txt")
        fake_tmux = FakeTmux(
            windows=[TmuxWindow(0, "alpha", 100, False)],
            pane_output={"alpha": output},
        )
        with patch.object(status, "TmuxOrchestrator", return_value=fake_tmux):
            result = status.get_team_status(team)
        assert result["workers"][0]["status"] == "waiting"

    def test_status_window_disappeared(self, isolated_config):
        cfg = isolated_config
        team = TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        worker = WorkerState(
            name="alpha", task="fix bug", provider="claude", mode="oneshot",
        )
        config.save_workers(team.name, [worker])
        # No windows at all — alpha disappeared
        fake_tmux = FakeTmux(windows=[], pane_output={})
        with patch.object(status, "TmuxOrchestrator", return_value=fake_tmux):
            result = status.get_team_status(team)
        assert result["workers"][0]["status"] == "error"
        assert "disappeared" in result["workers"][0]["last_error"]

    def test_status_pane_dead(self, isolated_config):
        cfg = isolated_config
        team = TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        worker = WorkerState(
            name="alpha", task="fix bug", provider="claude", mode="oneshot",
        )
        config.save_workers(team.name, [worker])
        fake_tmux = FakeTmux(
            windows=[TmuxWindow(0, "alpha", 100, True)],  # pane_dead=True
            pane_output={"alpha": ""},
        )
        with patch.object(status, "TmuxOrchestrator", return_value=fake_tmux):
            result = status.get_team_status(team)
        assert result["workers"][0]["status"] == "error"
        assert "pane exited" in result["workers"][0]["last_error"]

    def test_status_done_interactive_revives(self, isolated_config):
        cfg = isolated_config
        team = TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        worker = WorkerState(
            name="alpha", task="fix bug", provider="claude", mode="interactive",
            status="done",
        )
        config.save_workers(team.name, [worker])
        # Worker is "done" but pane is alive and showing active work
        output = load_sample("claude_interactive_working.txt")
        fake_tmux = FakeTmux(
            windows=[TmuxWindow(0, "alpha", 100, False)],
            pane_output={"alpha": output},
        )
        with patch.object(status, "TmuxOrchestrator", return_value=fake_tmux):
            result = status.get_team_status(team)
        assert result["workers"][0]["status"] == "running"
