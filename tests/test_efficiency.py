from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_team import cli, config, status, tmux


class SnapshotCachingTests(unittest.TestCase):
    def test_snapshot_reuses_window_and_pane_queries(self) -> None:
        class RecordingTmux(tmux.TmuxOrchestrator):
            def __init__(self) -> None:
                super().__init__("team-demo")
                self.calls: list[tuple[str, ...]] = []

            def _run(
                self,
                args: list[str],
                check: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                self.calls.append(tuple(args))
                if args[1] == "list-windows":
                    return subprocess.CompletedProcess(
                        args,
                        0,
                        "0\tworker\t123\t0\n",
                        "",
                    )
                if args[1] == "capture-pane":
                    return subprocess.CompletedProcess(
                        args,
                        0,
                        "\n".join(f"line {i}" for i in range(10)),
                        "",
                    )
                raise AssertionError(f"Unexpected tmux call: {args}")

        orchestrator = RecordingTmux()

        snapshot = orchestrator.get_snapshot(max_age=5)
        self.assertIs(snapshot, orchestrator.get_snapshot(max_age=5))

        tail10 = orchestrator.capture_pane("worker", lines=10, snapshot=snapshot)
        tail5 = orchestrator.capture_pane("worker", lines=5, snapshot=snapshot)

        self.assertEqual(tail10.splitlines()[0], "line 0")
        self.assertEqual(tail5.splitlines(), [f"line {i}" for i in range(5, 10)])
        self.assertEqual(
            sum(1 for call in orchestrator.calls if call[1] == "list-windows"),
            1,
        )
        self.assertEqual(
            sum(1 for call in orchestrator.calls if call[1] == "capture-pane"),
            1,
        )

    def test_resolve_target_cache_invalidates_after_multi_layout_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            multi_file = state_dir / "multi_targets"
            multi_file.write_text("host\nalice\nbob\n")

            orchestrator = tmux.TmuxOrchestrator("team-demo")

            self.assertEqual(orchestrator._resolve_target("bob", state_dir), "host.2")

            multi_file.write_text("new-host\nalice\nbob\n")
            self.assertEqual(orchestrator._resolve_target("bob", state_dir), "host.2")

            orchestrator._invalidate_state_cache(state_dir)
            self.assertEqual(orchestrator._resolve_target("bob", state_dir), "new-host.2")


class StatusTransitionTests(unittest.TestCase):
    def test_done_interactive_uses_snapshot_not_subprocess(self) -> None:
        """Re-evaluating done interactive workers should use the windows dict
        for pane_dead (from the snapshot) rather than calling is_pane_dead."""
        team = config.TeamConfig(name="demo", provider="codex")
        worker = config.WorkerState(
            name="worker",
            task="Do work",
            provider="codex",
            mode="interactive",
            status="done",
            tmux_window="worker",
        )
        tmux_snapshot = tmux.TmuxSnapshot(
            windows={"worker": tmux.TmuxWindow(0, "worker", 123, False)},
            pane_dead={"worker": False},
        )

        class FakeTmux:
            def get_snapshot(self, state_dir: Path | None = None, max_age: float = 0):
                return tmux_snapshot

            def list_windows(self, snapshot=None):
                active = snapshot or tmux_snapshot
                return list(active.windows.values())

            def deliver_pending_prompts(self, state_dir: Path, snapshot=None):
                return []

            def is_pane_dead(self, *args, **kwargs):
                raise AssertionError("should use windows dict, not is_pane_dead method")

            def capture_pane(self, target, lines=50, state_dir=None, snapshot=None):
                # Return output indicating Codex has finished
                return "Worked for 30 seconds\n\u203a "

        with tempfile.TemporaryDirectory() as tmpdir:
            state_root = Path(tmpdir)
            (state_root / team.name).mkdir(parents=True, exist_ok=True)
            with mock.patch.object(status, "STATE_DIR", state_root), mock.patch.object(
                status, "load_workers", return_value=[worker]
            ), mock.patch.object(status, "save_workers") as save_workers:
                result = status.get_team_status(team, tmux=FakeTmux())

        self.assertEqual(result["workers"][0]["status"], "done")
        save_workers.assert_not_called()


class CliEfficiencyTests(unittest.TestCase):
    def test_tail_log_lines_streams_large_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "worker.log"
            log_path.write_text("\n".join(f"line {i}" for i in range(200)) + "\n")

            with mock.patch("pathlib.Path.read_text", side_effect=AssertionError("read_text should not be used")):
                tail = cli._tail_log_lines(log_path, 3, small_file_limit=1)

        self.assertEqual(tail, ["line 197", "line 198", "line 199"])

    def test_sync_uses_parsed_worker_annotations(self) -> None:
        team = config.TeamConfig(name="demo", provider="codex")
        status_payload = {
            "workers": [
                {"name": "worker-one", "status": "done", "elapsed": "1m 00s"},
                {"name": "worker-two", "status": "running", "elapsed": "0m 30s"},
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            task_path = Path(tmpdir) / "tasks.md"
            task_path.write_text(
                "- [ ] first task ← worker-one | running | 0m 05s\n"
                "- [ ] second task ← worker-two | running | 0m 02s\n"
            )

            original_read_text = Path.read_text
            task_reads = 0

            def counting_read_text(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
                nonlocal task_reads
                if self == task_path:
                    task_reads += 1
                return original_read_text(self, *args, **kwargs)

            with mock.patch.object(cli, "_get_team", return_value=team), mock.patch.object(
                status, "get_team_status", return_value=status_payload
            ), mock.patch("pathlib.Path.read_text", new=counting_read_text):
                cli.sync.callback(str(task_path))

            self.assertEqual(task_reads, 2)
            self.assertEqual(
                task_path.read_text(),
                "- [x] first task ← worker-one | done | 1m 00s\n"
                "- [ ] second task ← worker-two | running | 0m 30s\n",
            )


if __name__ == "__main__":
    unittest.main()
