"""Tests for `team spawn-worker` command flows."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent / "src"))

from agentic_team import cli, config
from agentic_team.tmux import TmuxError

from conftest import FakeTmux, fake_health


def _setup_team(isolated_config, workers=None, provider="claude", use_worktrees=False):
    """Create a team with optional pre-existing workers."""
    cfg = isolated_config
    team = config.TeamConfig(name="demo", provider=provider, working_dir=str(cfg["workdir"]), use_worktrees=use_worktrees)
    config.save_team(team)
    config.save_workers("demo", workers or [])
    config.set_active_team("demo")
    config.create_session_log_dir("demo")
    return team


class TestSpawnWorker:
    def _invoke_spawn(self, args, fake_tmux=None):
        runner = CliRunner()
        fake_tmux = fake_tmux or FakeTmux(session_alive=True)

        with (
            patch("agentic_team.cli._ensure_tmux_available", return_value="tmux 3.4"),
            patch("agentic_team.cli._ensure_provider_ready", return_value=fake_health()),
            patch.object(cli, "_ensure_lead_started", return_value=fake_tmux),
            patch.object(cli.TmuxOrchestrator, "spawn_worker",
                         side_effect=fake_tmux.spawn_worker),
        ):
            result = runner.invoke(cli.app, ["spawn-worker"] + args)
        return result, fake_tmux

    def test_spawn_creates_worker_state(self, isolated_config):
        _setup_team(isolated_config)
        result, _ = self._invoke_spawn(["--task", "fix bug"])
        assert result.exit_code == 0
        workers = config.load_workers("demo")
        assert len(workers) == 1
        assert workers[0].task == "fix bug"
        assert workers[0].status == "running"

    def test_spawn_generates_name(self, isolated_config):
        _setup_team(isolated_config)
        result, _ = self._invoke_spawn(["--task", "Fix the login bug"])
        assert result.exit_code == 0
        workers = config.load_workers("demo")
        assert workers[0].name == "fix-login"

    def test_spawn_uses_custom_name(self, isolated_config):
        _setup_team(isolated_config)
        result, _ = self._invoke_spawn(["--task", "fix bug", "--name", "my-worker"])
        assert result.exit_code == 0
        workers = config.load_workers("demo")
        assert workers[0].name == "my-worker"

    def test_spawn_rejects_duplicate_name(self, isolated_config):
        _setup_team(isolated_config, workers=[
            config.WorkerState(name="alpha", task="existing"),
        ])
        result, _ = self._invoke_spawn(["--task", "new task", "--name", "alpha"])
        assert result.exit_code != 0
        assert "already in use" in result.output

    def test_spawn_rejects_max_workers(self, isolated_config):
        cfg = isolated_config
        team = config.TeamConfig(
            name="demo", provider="claude",
            working_dir=str(cfg["workdir"]), max_workers=1,
            use_worktrees=False,
        )
        config.save_team(team)
        config.save_workers("demo", [
            config.WorkerState(name="alpha", task="existing", status="running"),
        ])
        config.set_active_team("demo")
        config.create_session_log_dir("demo")

        result, _ = self._invoke_spawn(["--task", "new task"])
        assert result.exit_code != 0
        assert "max workers" in result.output.lower() or "Max workers" in result.output

    def test_spawn_inherits_team_defaults(self, isolated_config):
        _setup_team(isolated_config, provider="claude")
        result, fake_tmux = self._invoke_spawn(["--task", "fix bug"])
        assert result.exit_code == 0
        workers = config.load_workers("demo")
        assert workers[0].provider == "claude"

    def test_spawn_overrides_team_defaults(self, isolated_config):
        _setup_team(isolated_config, provider="claude")
        result, _ = self._invoke_spawn(["--task", "fix bug", "--provider", "codex"])
        assert result.exit_code == 0
        workers = config.load_workers("demo")
        assert workers[0].provider == "codex"

    def test_spawn_rollback_on_failure(self, isolated_config):
        _setup_team(isolated_config)
        runner = CliRunner()
        tmux_error = TmuxError(("tmux", "new-window"), 1, "spawn failed")
        # Use a real TmuxOrchestrator so class-level patch applies
        real_tmux = cli.TmuxOrchestrator("team-demo")

        with (
            patch("agentic_team.cli._ensure_tmux_available", return_value="tmux 3.4"),
            patch("agentic_team.cli._ensure_provider_ready", return_value=fake_health()),
            patch.object(cli, "_ensure_lead_started", return_value=real_tmux),
            patch.object(cli.TmuxOrchestrator, "spawn_worker", side_effect=tmux_error),
            patch.object(cli.TmuxOrchestrator, "kill_window"),
        ):
            result = runner.invoke(cli.app, ["spawn-worker", "--task", "demo task"])

        assert result.exit_code != 0
        assert config.load_workers("demo") == []
