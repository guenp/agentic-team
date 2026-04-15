"""Shared fixtures for the agentic-team test suite.

Provides FakeTmux (canned state, call recording), RecordingTmux
(subprocess arg recording), config isolation, and sample fixture
loading — none of which spawn real agents or tmux sessions.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent / "src"))

from agentic_team import config, status
from agentic_team.tmux import TmuxOrchestrator, TmuxSnapshot, TmuxWindow


SAMPLES_DIR = Path(__file__).parent / "samples"


# ── FakeTmux ────────────────────────────────────────────────────


class FakeTmux:
    """Drop-in replacement for TmuxOrchestrator in tests.

    Constructed with canned state; records all mutating calls for assertion.
    """

    def __init__(
        self,
        *,
        windows: list[TmuxWindow] | None = None,
        pane_output: dict[str, str] | None = None,
        dead_targets: set[str] | None = None,
        delivered: list[str] | None = None,
        session_alive: bool = True,
    ) -> None:
        self._windows = windows or []
        self._pane_output = pane_output or {}
        self._dead_targets = dead_targets or set()
        self._delivered = delivered or []
        self._session_alive = session_alive

        # Call recording
        self.sent_keys: list[tuple[str, str]] = []
        self.killed_windows: list[str] = []
        self.spawned_workers: list[dict] = []
        self.created_sessions: list[dict] = []

    def get_snapshot(
        self, state_dir: Path | None = None, max_age: float = 0,
    ) -> TmuxSnapshot:
        win_dict = {w.name: w for w in self._windows}
        pane_dead = {w.name: w.pane_dead for w in self._windows}
        pane_dead.update({t: True for t in self._dead_targets})
        return TmuxSnapshot(
            windows=win_dict,
            pane_dead=pane_dead,
        )

    def list_windows(self, snapshot: TmuxSnapshot | None = None) -> list[TmuxWindow]:
        return list(self._windows)

    def deliver_pending_prompts(
        self, state_dir: Path, snapshot: TmuxSnapshot | None = None,
    ) -> list[str]:
        return list(self._delivered)

    def capture_pane(
        self, target: str, lines: int = 50,
        state_dir: Path | None = None, snapshot: TmuxSnapshot | None = None,
    ) -> str:
        return self._pane_output.get(target, "")

    def capture_pane_safe(
        self, target: str, lines: int = 50,
        state_dir: Path | None = None, snapshot: TmuxSnapshot | None = None,
        retries: int = 2, context: str = "",
    ) -> str | None:
        return self._pane_output.get(target)

    def is_pane_dead(
        self, target: str, state_dir: Path | None = None,
        snapshot: TmuxSnapshot | None = None,
    ) -> bool:
        return target in self._dead_targets

    def session_exists(self) -> bool:
        return self._session_alive

    def send_keys(
        self, target: str, text: str, delay: float = 0,
        state_dir: Path | None = None,
    ) -> None:
        self.sent_keys.append((target, text))

    def kill_window(self, window_name: str) -> None:
        self.killed_windows.append(window_name)

    def kill_session(self) -> None:
        self._session_alive = False

    def spawn_worker(
        self, window_name: str, command: str, working_dir: str,
        state_dir: Path, provider_name: str, mode: str = "interactive",
        initial_prompt: str | None = None, timeout: int = 20,
    ) -> None:
        self.spawned_workers.append({
            "window_name": window_name,
            "command": command,
            "working_dir": working_dir,
            "provider_name": provider_name,
            "mode": mode,
            "initial_prompt": initial_prompt,
        })

    def create_session(
        self, working_dir: str, lead_command: str,
        provider_name: str | None = None, timeout: int = 20,
    ) -> None:
        self.created_sessions.append({
            "working_dir": working_dir,
            "lead_command": lead_command,
            "provider_name": provider_name,
        })

    @staticmethod
    def ensure_available() -> None:
        pass

    def send_shell_command(
        self, target: str, command: str, state_dir: Path | None = None,
    ) -> None:
        self.sent_keys.append((target, command))


# ── RecordingTmux ───────────────────────────────────────────────


class RecordingTmux(TmuxOrchestrator):
    """Subclass that records _run calls and returns canned results."""

    def __init__(self, session_name: str = "team-demo") -> None:
        super().__init__(session_name)
        self.calls: list[tuple[str, ...]] = []
        self.canned_results: dict[str, subprocess.CompletedProcess[str]] = {}

    def _run(
        self, args: list[str], check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(tuple(args))
        subcmd = args[1] if len(args) > 1 else ""
        if subcmd in self.canned_results:
            return self.canned_results[subcmd]
        return subprocess.CompletedProcess(args, 0, "", "")


# ── Config isolation fixture ────────────────────────────────────


@pytest.fixture
def isolated_config(tmp_path):
    """Patch all config/status path constants to use a temp directory."""
    root = tmp_path / "agentic-team"
    root.mkdir()
    teams_dir = root / "teams"
    state_dir = root / "state"
    logs_dir = root / "logs"
    active_link = root / "active"
    workdir = root / "repo"
    workdir.mkdir()

    patches = [
        patch.object(config, "BASE_DIR", root),
        patch.object(config, "TEAMS_DIR", teams_dir),
        patch.object(config, "STATE_DIR", state_dir),
        patch.object(config, "LOGS_DIR", logs_dir),
        patch.object(config, "ACTIVE_LINK", active_link),
        patch.object(status, "STATE_DIR", state_dir),
    ]
    for p in patches:
        p.start()

    yield {
        "root": root,
        "teams_dir": teams_dir,
        "state_dir": state_dir,
        "logs_dir": logs_dir,
        "active_link": active_link,
        "workdir": workdir,
    }

    for p in patches:
        p.stop()


# ── Sample fixture loader ───────────────────────────────────────


def load_sample(name: str) -> str:
    """Load a sample pane output fixture by filename."""
    path = SAMPLES_DIR / name
    return path.read_text()


# ── Fake provider health ────────────────────────────────────────

def fake_health(name: str = "claude", installed: bool = True, authenticated: bool = True):
    """Create a fake ProviderHealth for testing."""
    from agentic_team.models import ProviderHealth
    return ProviderHealth(
        name=name,
        cli_command=name,
        installed=installed,
        authenticated=authenticated,
        cli_path=f"/usr/bin/{name}" if installed else None,
        detail="ok",
        install_hint=f"Install {name}",
        login_hint=f"Login to {name}",
    )
