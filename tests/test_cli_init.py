"""Tests for `team init` command flows."""

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


class TestInitCommand:
    def _make_fake_tmux(self, session_exists=False):
        """Create a FakeTmux with overridden session_exists."""
        tmux = FakeTmux(session_alive=session_exists)
        return tmux

    def _invoke_init(self, isolated_config, extra_args=None, provider="claude",
                     tmux=None, health=None):
        cfg = isolated_config
        runner = CliRunner()
        tmux = tmux or self._make_fake_tmux()
        health = health or fake_health()
        args = ["init", "demo", "--working-dir", str(cfg["workdir"])]
        if provider:
            args.extend(["--provider", provider])
        if extra_args:
            args.extend(extra_args)

        with (
            patch("agentic_team.cli._ensure_tmux_available", return_value="tmux 3.4"),
            patch("agentic_team.cli._ensure_provider_ready", return_value=health),
            patch.object(cli.TmuxOrchestrator, "ensure_available"),
            patch.object(cli.TmuxOrchestrator, "session_exists", return_value=tmux._session_alive),
            patch.object(cli.TmuxOrchestrator, "create_session", side_effect=tmux.create_session),
            patch.object(cli.TmuxOrchestrator, "kill_session", side_effect=tmux.kill_session),
        ):
            result = runner.invoke(cli.app, args)
        return result

    def test_init_creates_config_and_workers(self, isolated_config):
        cfg = isolated_config
        result = self._invoke_init(isolated_config)
        assert result.exit_code == 0
        # Team config file exists
        assert (cfg["teams_dir"] / "demo.toml").exists()
        # Workers file exists (empty)
        assert (cfg["state_dir"] / "demo" / "workers.toml").exists()
        # Active link points to team
        assert config.get_active_team_name() == "demo"

    def test_init_creates_session_log_dir(self, isolated_config):
        cfg = isolated_config
        self._invoke_init(isolated_config)
        current_link = cfg["logs_dir"] / "demo" / "current"
        assert current_link.is_symlink()

    def test_init_rollback_on_tmux_failure(self, isolated_config):
        cfg = isolated_config
        runner = CliRunner()
        tmux_error = TmuxError(("tmux", "new-session"), 1, "session creation failed")

        with (
            patch("agentic_team.cli._resolve_provider_choice", return_value=("claude", False)),
            patch("agentic_team.cli._ensure_tmux_available", return_value="tmux 3.4"),
            patch("agentic_team.cli._ensure_provider_ready", return_value=fake_health()),
            patch.object(cli.TmuxOrchestrator, "ensure_available"),
            patch.object(cli.TmuxOrchestrator, "session_exists", return_value=False),
            patch.object(cli.TmuxOrchestrator, "create_session", side_effect=tmux_error),
            patch.object(cli.TmuxOrchestrator, "kill_session"),
        ):
            result = runner.invoke(cli.app, [
                "init", "demo", "--working-dir", str(cfg["workdir"]),
            ])

        assert result.exit_code != 0
        assert not (cfg["teams_dir"] / "demo.toml").exists()
        assert not (cfg["state_dir"] / "demo" / "workers.toml").exists()
        assert not cfg["active_link"].exists()

    def test_init_worktree_flag(self, isolated_config):
        """--worktree sets use_worktrees=True in the saved config."""
        result = self._invoke_init(isolated_config, extra_args=["--worktree"])
        assert result.exit_code == 0
        team = config.load_team("demo")
        assert team.use_worktrees is True

    def test_init_default_no_worktree(self, isolated_config):
        """Without --worktree, use_worktrees defaults to False."""
        result = self._invoke_init(isolated_config)
        assert result.exit_code == 0
        team = config.load_team("demo")
        assert team.use_worktrees is False

    def test_init_rejects_running_team(self, isolated_config):
        cfg = isolated_config
        # Pre-create the team so it looks like it already exists
        team = config.TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        config.save_team(team)

        runner = CliRunner()
        with (
            patch("agentic_team.cli._ensure_tmux_available", return_value="tmux 3.4"),
            patch("agentic_team.cli._ensure_provider_ready", return_value=fake_health()),
            patch.object(cli.TmuxOrchestrator, "ensure_available"),
            patch.object(cli.TmuxOrchestrator, "session_exists", return_value=True),
        ):
            result = runner.invoke(cli.app, [
                "init", "demo", "--provider", "claude",
                "--working-dir", str(cfg["workdir"]),
            ])
        assert result.exit_code != 0
        assert "already running" in result.output.lower() or "already" in result.output.lower()
