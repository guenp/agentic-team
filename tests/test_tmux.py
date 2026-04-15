"""Tests for TmuxOrchestrator command dispatch using RecordingTmux.

Verifies the exact subprocess args that would be sent to tmux
without requiring a real tmux server.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent / "src"))

from agentic_team.tmux import EXIT_SENTINEL, TmuxOrchestrator, TmuxSnapshot, TmuxWindow

from conftest import RecordingTmux


class TestCreateSession:
    def test_create_session_command(self):
        rec = RecordingTmux("team-demo")
        # Provide canned results for the commands create_session uses
        rec.canned_results["has-session"] = subprocess.CompletedProcess([], 1, "", "")
        rec.canned_results["list-windows"] = subprocess.CompletedProcess(
            [], 0, "0\tlead\t123\t0\n", "",
        )
        rec.canned_results["capture-pane"] = subprocess.CompletedProcess(
            [], 0, "Claude Code\nready", "",
        )

        rec.create_session("/tmp/repo", "claude --verbose", provider_name=None, timeout=0)

        # Find the new-session call
        new_session_calls = [c for c in rec.calls if "new-session" in c]
        assert len(new_session_calls) == 1
        call = new_session_calls[0]
        assert "-d" in call
        assert "-s" in call
        assert "team-demo" in call
        assert "-n" in call
        assert "lead" in call
        assert "-x" in call
        assert "220" in call
        assert "-y" in call
        assert "50" in call

    def test_create_session_sets_options(self):
        rec = RecordingTmux("team-demo")
        rec.create_session("/tmp/repo", "claude", provider_name=None, timeout=0)

        set_option_calls = [c for c in rec.calls if "set-option" in c]
        option_texts = [" ".join(c) for c in set_option_calls]
        assert any("allow-rename" in t and "off" in t for t in option_texts)
        assert any("window-size" in t and "smallest" in t for t in option_texts)


class TestWindowManagement:
    def test_create_window_command(self):
        rec = RecordingTmux("team-demo")
        rec.create_window("worker-1", "/tmp/repo")

        new_window_calls = [c for c in rec.calls if "new-window" in c]
        assert len(new_window_calls) == 1
        call = new_window_calls[0]
        assert "-t" in call
        assert "team-demo" in call
        assert "-n" in call
        assert "worker-1" in call
        assert "-c" in call

    def test_kill_window_command(self):
        rec = RecordingTmux("team-demo")
        rec.kill_window("worker-1")

        kill_calls = [c for c in rec.calls if "kill-window" in c]
        assert len(kill_calls) == 1
        assert "team-demo:worker-1" in kill_calls[0]


class TestSendKeys:
    def test_send_keys_literal(self):
        rec = RecordingTmux("team-demo")
        rec.send_keys("lead", "hello world")

        send_calls = [c for c in rec.calls if "send-keys" in c]
        assert len(send_calls) == 2  # literal text + Enter
        # First call: literal text
        assert "-l" in send_calls[0]
        assert "hello world" in send_calls[0]
        # Second call: Enter
        assert "Enter" in send_calls[1]

    def test_send_shell_command_wraps_exit(self):
        rec = RecordingTmux("team-demo")
        rec.send_shell_command("lead", "echo hello")

        send_calls = [c for c in rec.calls if "send-keys" in c]
        # The wrapped command should contain the exit sentinel
        text_call = send_calls[0]
        joined = " ".join(text_call)
        assert EXIT_SENTINEL in joined


class TestCapture:
    def test_capture_pane_command(self):
        rec = RecordingTmux("team-demo")
        rec.canned_results["capture-pane"] = subprocess.CompletedProcess(
            [], 0, "line1\nline2\n", "",
        )
        result = rec.capture_pane("worker", lines=50)

        capture_calls = [c for c in rec.calls if "capture-pane" in c]
        assert len(capture_calls) == 1
        call = capture_calls[0]
        assert "-t" in call
        assert "team-demo:worker" in call
        assert "-p" in call
        assert "-S" in call
        assert "-50" in call

    def test_list_windows_format(self):
        rec = RecordingTmux("team-demo")
        rec.canned_results["list-windows"] = subprocess.CompletedProcess(
            [], 0, "0\tlead\t100\t0\n1\tworker\t200\t0\n", "",
        )
        windows = rec.list_windows()

        list_calls = [c for c in rec.calls if "list-windows" in c]
        assert len(list_calls) == 1
        call = list_calls[0]
        assert "-t" in call
        assert "team-demo" in call
        assert "-F" in call
        assert len(windows) == 2
        assert windows[0].name == "lead"
        assert windows[1].name == "worker"


class TestResolveTarget:
    def test_resolve_target_multi_mode(self, tmp_path):
        multi_file = tmp_path / "multi_targets"
        multi_file.write_text("host\nalice\nbob\n")
        rec = RecordingTmux("team-demo")
        result = rec._resolve_target("bob", tmp_path)
        assert result == "host.2"

    def test_resolve_target_no_multi(self, tmp_path):
        rec = RecordingTmux("team-demo")
        result = rec._resolve_target("worker", tmp_path)
        assert result == "worker"


class TestCapturePaneSafe:
    def test_capture_pane_safe_returns_none_on_failure(self):
        from agentic_team.tmux import TmuxError

        class FailingTmux(TmuxOrchestrator):
            def _run(self, args, check=True):
                if "capture-pane" in args:
                    raise TmuxError(
                        command=tuple(args), returncode=1, stderr="pane not found",
                    )
                return subprocess.CompletedProcess(args, 0, "", "")

        tmux = FailingTmux("team-demo")
        result = tmux.capture_pane_safe("worker", lines=50, retries=2, context="test")
        assert result is None


class TestKillSession:
    def test_kill_session_command(self):
        rec = RecordingTmux("team-demo")
        # Make session_exists return True
        rec.canned_results["has-session"] = subprocess.CompletedProcess([], 0, "", "")
        rec.kill_session()

        kill_calls = [c for c in rec.calls if "kill-session" in c]
        assert len(kill_calls) == 1
        assert "team-demo" in kill_calls[0]
