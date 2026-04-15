from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_team import cli, config, status, taskfile  # noqa: E402
from agentic_team.tmux import TmuxError, TmuxWindow  # noqa: E402


class FakeTmux:
    def __init__(
        self,
        *,
        windows: list[TmuxWindow] | None = None,
        pane_output: dict[str, str] | None = None,
        dead_targets: set[str] | None = None,
        delivered: list[str] | None = None,
    ) -> None:
        self._windows = windows or []
        self._pane_output = pane_output or {}
        self._dead_targets = dead_targets or set()
        self._delivered = delivered or []

    def list_windows(self) -> list[TmuxWindow]:
        return self._windows

    def deliver_pending_prompts(self, state_dir: Path) -> list[str]:
        return list(self._delivered)

    def capture_pane(self, target: str, lines: int = 50, state_dir: Path | None = None) -> str:
        return self._pane_output.get(target, "")

    def capture_pane_safe(
        self, target: str, lines: int = 50, state_dir: Path | None = None,
        retries: int = 2, context: str = "",
    ) -> str | None:
        return self._pane_output.get(target)

    def is_pane_dead(self, target: str, state_dir: Path | None = None) -> bool:
        return target in self._dead_targets


class RobustnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name)
        self.teams_dir = self.root / "teams"
        self.state_dir = self.root / "state"
        self.logs_dir = self.root / "logs"
        self.active_link = self.root / "active"
        self.workdir = self.root / "repo"
        self.workdir.mkdir()

        patches = [
            patch.object(config, "BASE_DIR", self.root),
            patch.object(config, "TEAMS_DIR", self.teams_dir),
            patch.object(config, "STATE_DIR", self.state_dir),
            patch.object(config, "LOGS_DIR", self.logs_dir),
            patch.object(config, "ACTIVE_LINK", self.active_link),
            patch.object(status, "STATE_DIR", self.state_dir),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_load_workers_invalid_toml_has_recovery_guidance(self) -> None:
        workers_path = self.state_dir / "demo" / "workers.toml"
        workers_path.parent.mkdir(parents=True, exist_ok=True)
        workers_path.write_text("workers = [\n")

        with self.assertRaises(config.StateFileError) as ctx:
            config.load_workers("demo")

        self.assertIn("Could not parse", str(ctx.exception))
        self.assertIn("Fix the TOML or remove the file", str(ctx.exception))

    def test_parse_task_file_wraps_read_errors(self) -> None:
        missing = self.root / "missing.md"

        with self.assertRaises(taskfile.TaskFileError) as ctx:
            taskfile.parse_task_file(missing)

        self.assertIn("Could not read task file", str(ctx.exception))

    def test_status_marks_nonzero_exit_as_error(self) -> None:
        team = config.TeamConfig(name="demo", provider="claude", working_dir=str(self.workdir))
        worker = config.WorkerState(
            name="alpha",
            task="run tests",
            provider="claude",
            mode="oneshot",
            status="running",
        )
        config.save_workers(team.name, [worker])
        fake_tmux = FakeTmux(
            windows=[TmuxWindow(index=0, name="alpha", pane_pid=100, pane_dead=False)],
            pane_output={
                "alpha": "\n".join([
                    "$ claude --print run tests",
                    "zsh: command not found: claude",
                    "__AGENTIC_TEAM_EXIT__=127",
                    "%",
                ]),
            },
        )

        with patch.object(status, "TmuxOrchestrator", return_value=fake_tmux):
            st = status.get_team_status(team)

        worker_status = st["workers"][0]
        self.assertEqual(worker_status["status"], "error")
        self.assertEqual(worker_status["exit_code"], 127)
        self.assertIn("not found", worker_status["last_error"])

    def test_status_marks_prompt_delivery_timeout_as_error(self) -> None:
        team = config.TeamConfig(name="demo", provider="codex", working_dir=str(self.workdir))
        worker = config.WorkerState(
            name="beta",
            task="fix bug",
            provider="codex",
            mode="interactive",
            status="running",
        )
        config.save_workers(team.name, [worker])
        prompt_file = self.state_dir / team.name / "pending_prompts" / worker.name
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("fix bug")
        stale = time.time() - (status.PROMPT_DELIVERY_TIMEOUT_SECONDS + 5)
        os.utime(prompt_file, (stale, stale))

        fake_tmux = FakeTmux(
            windows=[TmuxWindow(index=0, name="beta", pane_pid=101, pane_dead=False)],
            pane_output={"beta": "OpenAI Codex\nstill starting"},
        )

        with patch.object(status, "TmuxOrchestrator", return_value=fake_tmux):
            st = status.get_team_status(team)

        worker_status = st["workers"][0]
        self.assertEqual(worker_status["status"], "error")
        self.assertIn("not delivered", worker_status["last_error"])

    def test_cli_converts_tmux_errors_without_traceback(self) -> None:
        runner = CliRunner()
        tmux_error = TmuxError(("tmux",), None, "tmux is not installed")

        with patch.object(cli.TmuxOrchestrator, "ensure_available", side_effect=tmux_error):
            result = runner.invoke(cli.app, ["init", "demo", "--working-dir", str(self.workdir)])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("tmux", result.output)
        self.assertNotIn("Traceback", result.output)

    def test_init_rolls_back_state_when_tmux_creation_fails(self) -> None:
        runner = CliRunner()
        tmux_error = TmuxError(("tmux", "new-session"), 1, "session creation failed")

        with (
            patch.object(cli.TmuxOrchestrator, "ensure_available", return_value=None),
            patch.object(cli.TmuxOrchestrator, "session_exists", return_value=False),
            patch.object(cli.TmuxOrchestrator, "create_session", side_effect=tmux_error),
            patch.object(cli.TmuxOrchestrator, "kill_session", return_value=None),
        ):
            result = runner.invoke(cli.app, ["init", "demo", "--working-dir", str(self.workdir)])

        self.assertNotEqual(result.exit_code, 0)
        self.assertFalse((self.teams_dir / "demo.toml").exists())
        self.assertFalse((self.state_dir / "demo" / "workers.toml").exists())
        self.assertFalse(self.active_link.exists())
        self.assertFalse((self.logs_dir / "demo" / "current").exists())

    def test_spawn_worker_rolls_back_saved_state_when_tmux_spawn_fails(self) -> None:
        runner = CliRunner()
        team = config.TeamConfig(name="demo", provider="claude", working_dir=str(self.workdir))
        config.save_workers(team.name, [])

        with (
            patch.object(cli, "_get_team", return_value=team),
            patch.object(cli.TmuxOrchestrator, "ensure_available", return_value=None),
            patch.object(cli.TmuxOrchestrator, "session_exists", return_value=True),
            patch.object(
                cli.TmuxOrchestrator,
                "spawn_worker",
                side_effect=TmuxError(("tmux", "new-window"), 1, "spawn failed"),
            ),
            patch.object(cli.TmuxOrchestrator, "kill_window", return_value=None),
        ):
            result = runner.invoke(cli.app, ["spawn-worker", "--task", "demo task"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(config.load_workers(team.name), [])


if __name__ == "__main__":
    unittest.main()
