"""Tests for the `team prompt` CLI command."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent / "src"))

from agentic_team import agents, cli, config

from conftest import FakeTmux


class TestPromptCommand:
    def test_prompt_sends_to_lead(self, isolated_config):
        cfg = isolated_config
        team = config.TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        config.save_team(team)
        config.set_active_team("demo")

        fake_tmux = FakeTmux(session_alive=True)
        runner = CliRunner()
        with patch.object(cli, "TmuxOrchestrator", return_value=fake_tmux):
            result = runner.invoke(cli.app, ["prompt"])
        assert result.exit_code == 0
        assert "re-sent" in result.output.lower()

        # Verify send_keys was called on the lead pane
        assert len(fake_tmux.sent_keys) == 1
        target, text = fake_tmux.sent_keys[0]
        assert target == "lead"
        assert "SYSTEM PROMPT REMINDER" in text
        assert "spawn-worker" in text  # prompt body includes commands

    def test_prompt_dry_run_prints_to_stdout(self, isolated_config):
        cfg = isolated_config
        team = config.TeamConfig(
            name="demo", provider="claude", max_workers=4,
            working_dir=str(cfg["workdir"]),
        )
        config.save_team(team)
        config.set_active_team("demo")

        runner = CliRunner()
        result = runner.invoke(cli.app, ["prompt", "--dry-run"])
        assert result.exit_code == 0
        # Should print the prompt body, not the "re-sent" message
        assert "spawn-worker" in result.output
        assert "re-sent" not in result.output.lower()
        assert "4" in result.output  # max_workers

    def test_prompt_custom_file(self, isolated_config, tmp_path):
        cfg = isolated_config
        team = config.TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        config.save_team(team)
        config.set_active_team("demo")

        custom_file = tmp_path / "custom-prompt.txt"
        custom_file.write_text("You are a custom lead agent. Do special things.")

        fake_tmux = FakeTmux(session_alive=True)
        runner = CliRunner()
        with patch.object(cli, "TmuxOrchestrator", return_value=fake_tmux):
            result = runner.invoke(cli.app, ["prompt", "--custom", str(custom_file)])
        assert result.exit_code == 0
        assert "re-sent" in result.output.lower()

        target, text = fake_tmux.sent_keys[0]
        assert "custom lead agent" in text
        # Should NOT contain the default system prompt commands
        assert "spawn-worker" not in text

    def test_prompt_custom_dry_run(self, isolated_config, tmp_path):
        cfg = isolated_config
        team = config.TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        config.save_team(team)
        config.set_active_team("demo")

        custom_file = tmp_path / "custom-prompt.txt"
        custom_file.write_text("Custom prompt content here.")

        runner = CliRunner()
        result = runner.invoke(cli.app, ["prompt", "--dry-run", "--custom", str(custom_file)])
        assert result.exit_code == 0
        assert "Custom prompt content here." in result.output

    def test_prompt_fails_no_session(self, isolated_config):
        cfg = isolated_config
        team = config.TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        config.save_team(team)
        config.set_active_team("demo")

        fake_tmux = FakeTmux(session_alive=False)
        runner = CliRunner()
        with patch.object(cli, "TmuxOrchestrator", return_value=fake_tmux):
            result = runner.invoke(cli.app, ["prompt"])
        assert result.exit_code != 0
        assert "not running" in result.output.lower()

    def test_prompt_reflects_current_config(self, isolated_config):
        """The prompt should use current config values, not cached ones."""
        cfg = isolated_config
        team = config.TeamConfig(
            name="demo", provider="claude", max_workers=12,
            working_dir="/special/path",
        )
        config.save_team(team)
        config.set_active_team("demo")

        runner = CliRunner()
        result = runner.invoke(cli.app, ["prompt", "--dry-run"])
        assert result.exit_code == 0
        assert "12" in result.output
        assert "/special/path" in result.output

    def test_prompt_preamble_framing(self, isolated_config):
        """The sent message should have the preamble before the prompt body."""
        cfg = isolated_config
        team = config.TeamConfig(name="demo", provider="claude", working_dir=str(cfg["workdir"]))
        config.save_team(team)
        config.set_active_team("demo")

        fake_tmux = FakeTmux(session_alive=True)
        runner = CliRunner()
        with patch.object(cli, "TmuxOrchestrator", return_value=fake_tmux):
            result = runner.invoke(cli.app, ["prompt"])
        assert result.exit_code == 0

        _, text = fake_tmux.sent_keys[0]
        # Preamble should come before the prompt body
        preamble_idx = text.index("SYSTEM PROMPT REMINDER")
        body_idx = text.index("You are the lead agent")
        assert preamble_idx < body_idx
