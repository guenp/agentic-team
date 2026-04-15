"""Tests for `team run` and `team sync` task file flows."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent / "src"))

from agentic_team import cli, config, status

from conftest import FakeTmux, fake_health


def _setup_team(isolated_config, workers=None, provider="claude"):
    cfg = isolated_config
    team = config.TeamConfig(name="demo", provider=provider, working_dir=str(cfg["workdir"]), use_worktrees=False)
    config.save_team(team)
    config.save_workers("demo", workers or [])
    config.set_active_team("demo")
    config.create_session_log_dir("demo")
    return team


class TestRunCommand:
    def _invoke_run(self, task_file, extra_args=None, fake_tmux=None):
        runner = CliRunner()
        fake_tmux = fake_tmux or FakeTmux(session_alive=True)
        args = ["run", str(task_file)]
        if extra_args:
            args.extend(extra_args)

        with (
            patch("agentic_team.cli._ensure_tmux_available", return_value="tmux 3.4"),
            patch("agentic_team.cli._ensure_provider_ready", return_value=fake_health()),
            patch.object(cli, "_ensure_lead_started", return_value=fake_tmux),
            patch.object(cli.TmuxOrchestrator, "spawn_worker",
                         side_effect=fake_tmux.spawn_worker),
        ):
            result = runner.invoke(cli.app, args)
        return result, fake_tmux

    def test_run_spawns_unchecked_tasks(self, isolated_config):
        _setup_team(isolated_config)
        task_file = isolated_config["workdir"] / "tasks.md"
        task_file.write_text(
            "- [ ] Fix bug\n"
            "- [ ] Add tests\n"
            "- [ ] Update docs\n"
        )
        result, fake_tmux = self._invoke_run(task_file)
        assert result.exit_code == 0
        assert len(fake_tmux.spawned_workers) == 3

    def test_run_skips_checked_tasks(self, isolated_config):
        _setup_team(isolated_config)
        task_file = isolated_config["workdir"] / "tasks.md"
        task_file.write_text(
            "- [x] Already done\n"
            "- [ ] Pending task\n"
        )
        result, fake_tmux = self._invoke_run(task_file)
        assert result.exit_code == 0
        assert len(fake_tmux.spawned_workers) == 1

    def test_run_respects_limit(self, isolated_config):
        _setup_team(isolated_config)
        task_file = isolated_config["workdir"] / "tasks.md"
        task_file.write_text(
            "- [ ] Task 1\n"
            "- [ ] Task 2\n"
            "- [ ] Task 3\n"
        )
        result, fake_tmux = self._invoke_run(task_file, ["--limit", "2"])
        assert result.exit_code == 0
        assert len(fake_tmux.spawned_workers) == 2

    def test_run_dry_run(self, isolated_config):
        _setup_team(isolated_config)
        task_file = isolated_config["workdir"] / "tasks.md"
        task_file.write_text("- [ ] Fix bug\n- [ ] Add tests\n")
        result, fake_tmux = self._invoke_run(task_file, ["--dry-run"])
        assert result.exit_code == 0
        assert len(fake_tmux.spawned_workers) == 0
        assert "Fix bug" in result.output or "plan" in result.output.lower()


class TestSyncCommand:
    def test_sync_ticks_done_tasks(self, isolated_config):
        _setup_team(isolated_config)
        task_file = isolated_config["workdir"] / "tasks.md"
        task_file.write_text(
            "- [ ] Fix bug \u2190 alpha | running | 0m 30s\n"
            "- [ ] Add tests \u2190 bravo | running | 0m 15s\n"
        )
        status_payload = {
            "workers": [
                {"name": "alpha", "status": "done", "elapsed": "2m 00s"},
                {"name": "bravo", "status": "running", "elapsed": "1m 00s"},
            ],
        }
        runner = CliRunner()
        with (
            patch.object(cli, "_get_team", return_value=config.TeamConfig(name="demo", provider="claude")),
            patch.object(status, "get_team_status", return_value=status_payload),
        ):
            result = runner.invoke(cli.app, ["sync", str(task_file)])
        assert result.exit_code == 0
        content = task_file.read_text()
        assert "- [x] Fix bug" in content
        assert "- [ ] Add tests" in content

    def test_sync_updates_annotations(self, isolated_config):
        _setup_team(isolated_config)
        task_file = isolated_config["workdir"] / "tasks.md"
        task_file.write_text(
            "- [ ] Fix bug \u2190 alpha | running | 0m 05s\n"
        )
        status_payload = {
            "workers": [
                {"name": "alpha", "status": "done", "elapsed": "2m 30s"},
            ],
        }
        runner = CliRunner()
        with (
            patch.object(cli, "_get_team", return_value=config.TeamConfig(name="demo", provider="claude")),
            patch.object(status, "get_team_status", return_value=status_payload),
        ):
            result = runner.invoke(cli.app, ["sync", str(task_file)])
        assert result.exit_code == 0
        content = task_file.read_text()
        assert "\u2190 alpha | done | 2m 30s" in content
