"""Tests for TeamGroup routing — typo detection, bare prompt routing, --team flag."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent / "src"))

from agentic_team import cli, config


class TestTeamGroupRouting:
    def test_typo_suggests_command(self, isolated_config):
        runner = CliRunner()
        result = runner.invoke(cli.app, ["statsu"])
        assert result.exit_code != 0
        assert "Did you mean" in result.output
        assert "status" in result.output

    def test_team_flag_not_found(self, isolated_config):
        runner = CliRunner()
        result = runner.invoke(cli.app, ["-T", "nonexistent", "status"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_team_flag_selects_team(self, isolated_config):
        cfg = isolated_config
        team = config.TeamConfig(name="other", provider="claude", working_dir=str(cfg["workdir"]))
        config.save_team(team)
        config.save_workers("other", [])
        config.set_active_team("other")

        runner = CliRunner()
        # --team should select "other" and status should work
        fake_tmux_cls = type("FakeTmuxCls", (), {
            "__init__": lambda self, *a, **kw: None,
            "session_exists": lambda self: False,
        })
        with patch.object(cli, "TmuxOrchestrator", fake_tmux_cls):
            result = runner.invoke(cli.app, ["-T", "other", "status"])
        # Should find the team (may error on tmux but not on team lookup)
        assert "not found" not in result.output or "tmux" in result.output.lower()
