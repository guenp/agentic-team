"""Tests for CLI commands — send, status, logs, stop-worker, clear, stop, list."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent / "src"))

from agentic_team import cli, config, status
from agentic_team.tmux import TmuxWindow

from conftest import FakeTmux, fake_health


class TestSendCommand:
    def test_send_dispatches_to_lead(self, isolated_config):
        cfg = isolated_config
        team = config.TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        config.save_team(team)
        config.set_active_team("demo")

        fake_tmux = FakeTmux(session_alive=True)
        runner = CliRunner()
        with patch.object(cli, "TmuxOrchestrator", return_value=fake_tmux):
            result = runner.invoke(cli.app, ["send", "hello world"])
        assert result.exit_code == 0
        assert ("lead", "hello world") in fake_tmux.sent_keys

    def test_send_fails_no_session(self, isolated_config):
        cfg = isolated_config
        team = config.TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        config.save_team(team)
        config.set_active_team("demo")

        fake_tmux = FakeTmux(session_alive=False)
        runner = CliRunner()
        with patch.object(cli, "TmuxOrchestrator", return_value=fake_tmux):
            result = runner.invoke(cli.app, ["send", "hello"])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestStatusCommand:
    def test_status_prints_table(self, isolated_config):
        cfg = isolated_config
        team = config.TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        config.save_team(team)
        config.set_active_team("demo")

        status_payload = {
            "team": "demo",
            "session": "team-demo",
            "lead_active": True,
            "workers": [
                {"name": "alpha", "provider": "claude", "mode": "interactive",
                 "status": "running", "task": "fix bug", "source": "cli",
                 "elapsed": "1m 00s", "last_error": None, "exit_code": None},
            ],
        }
        runner = CliRunner()
        with (
            patch.object(status, "get_team_status", return_value=status_payload),
            patch.object(cli, "TmuxOrchestrator", return_value=FakeTmux()),
        ):
            result = runner.invoke(cli.app, ["status"])
        assert result.exit_code == 0
        assert "alpha" in result.output


class TestLogsCommand:
    def test_logs_reads_log_file(self, isolated_config):
        cfg = isolated_config
        team = config.TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        config.save_team(team)
        config.set_active_team("demo")
        config.save_workers("demo", [
            config.WorkerState(name="alpha", task="fix bug"),
        ])

        # Create log file
        session_dir = config.create_session_log_dir("demo")
        log_file = session_dir / "alpha.log"
        log_file.write_text("log line 1\nlog line 2\nlog line 3\n")

        runner = CliRunner()
        result = runner.invoke(cli.app, ["logs", "alpha"])
        assert result.exit_code == 0
        assert "log line" in result.output

    def test_logs_partial_name_match(self, isolated_config):
        cfg = isolated_config
        team = config.TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        config.save_team(team)
        config.set_active_team("demo")
        config.save_workers("demo", [
            config.WorkerState(name="fix-auth", task="fix auth"),
        ])

        session_dir = config.create_session_log_dir("demo")
        log_file = session_dir / "fix-auth.log"
        log_file.write_text("auth log output\n")

        runner = CliRunner()
        result = runner.invoke(cli.app, ["logs", "fix"])
        assert result.exit_code == 0
        assert "auth log output" in result.output


class TestStopWorker:
    def test_stop_worker_kills_window(self, isolated_config):
        cfg = isolated_config
        team = config.TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        config.save_team(team)
        config.set_active_team("demo")
        config.save_workers("demo", [
            config.WorkerState(name="alpha", task="fix bug", status="running"),
        ])

        fake_tmux = FakeTmux(session_alive=True)
        runner = CliRunner()
        with patch.object(cli, "TmuxOrchestrator", return_value=fake_tmux):
            result = runner.invoke(cli.app, ["stop-worker", "alpha"])
        assert result.exit_code == 0
        assert "alpha" in fake_tmux.killed_windows

        # Worker should be marked done
        workers = config.load_workers("demo")
        assert workers[0].status == "done"


class TestClearCommand:
    def test_clear_removes_done_workers(self, isolated_config):
        cfg = isolated_config
        team = config.TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        config.save_team(team)
        config.set_active_team("demo")
        config.save_workers("demo", [
            config.WorkerState(name="alpha", task="fix bug", status="done"),
            config.WorkerState(name="bravo", task="add tests", status="running"),
        ])

        fake_tmux = FakeTmux(session_alive=True)
        runner = CliRunner()
        with patch.object(cli, "TmuxOrchestrator", return_value=fake_tmux):
            result = runner.invoke(cli.app, ["clear"])
        assert result.exit_code == 0

        # Only running worker remains
        workers = config.load_workers("demo")
        assert len(workers) == 1
        assert workers[0].name == "bravo"


class TestStopCommand:
    def test_stop_kills_session(self, isolated_config):
        cfg = isolated_config
        team = config.TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        config.save_team(team)
        config.set_active_team("demo")
        config.save_workers("demo", [])

        fake_tmux = FakeTmux(session_alive=True)
        runner = CliRunner()
        with patch.object(cli, "TmuxOrchestrator", return_value=fake_tmux):
            result = runner.invoke(cli.app, ["stop"])
        assert result.exit_code == 0
        assert fake_tmux._session_alive is False
        # Active link should be cleared
        assert config.get_active_team_name() is None


class TestListCommand:
    def test_list_shows_teams(self, isolated_config):
        cfg = isolated_config
        team1 = config.TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        team2 = config.TeamConfig(name="other", provider="codex", working_dir=str(cfg["workdir"]))
        config.save_team(team1)
        config.save_team(team2)

        runner = CliRunner()
        with patch.object(cli, "TmuxOrchestrator") as MockTmux:
            MockTmux.return_value.session_exists.return_value = False
            result = runner.invoke(cli.app, ["list"])
        assert result.exit_code == 0
        assert "demo" in result.output
        assert "other" in result.output
