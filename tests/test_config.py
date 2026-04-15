"""Tests for TeamConfig, WorkerState, TOML persistence, and active team management."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent / "src"))

from agentic_team.config import (
    StateFileError,
    TeamConfig,
    WorkerState,
    clear_active_team,
    create_session_log_dir,
    current_session_log_dir,
    get_active_team,
    get_active_team_name,
    load_team,
    load_workers,
    save_team,
    save_workers,
    set_active_team,
    _atomic_write_bytes,
)


class TestTeamConfigDataclass:
    def test_team_config_defaults(self):
        tc = TeamConfig(name="demo", provider="claude")
        assert tc.worker_mode == "interactive"
        assert tc.permissions == "auto"
        assert tc.max_workers == 6

    def test_team_config_tmux_session(self):
        tc = TeamConfig(name="demo", provider="claude")
        assert tc.tmux_session == "team-demo"

    def test_team_config_created_at_auto(self):
        tc = TeamConfig(name="demo", provider="claude")
        assert tc.created_at  # non-empty
        assert "T" in tc.created_at  # ISO format


class TestWorkerStateDataclass:
    def test_worker_state_defaults(self):
        ws = WorkerState(name="alpha", task="fix bug")
        assert ws.status == "running"
        assert ws.source == "cli"
        assert ws.tmux_window == "alpha"

    def test_worker_state_started_at_auto(self):
        ws = WorkerState(name="alpha", task="fix bug")
        assert ws.started_at
        assert "T" in ws.started_at


class TestTomlRoundTrip:
    def test_save_load_team_roundtrip(self, isolated_config):
        tc = TeamConfig(name="demo", provider="claude", model="opus")
        save_team(tc)
        loaded = load_team("demo")
        assert loaded.name == tc.name
        assert loaded.provider == tc.provider
        assert loaded.model == tc.model
        assert loaded.worker_mode == tc.worker_mode

    def test_save_load_workers_roundtrip(self, isolated_config):
        workers = [
            WorkerState(name="alpha", task="fix bug", provider="claude"),
            WorkerState(name="bravo", task="add tests", provider="codex"),
        ]
        save_workers("demo", workers)
        loaded = load_workers("demo")
        assert len(loaded) == 2
        assert loaded[0].name == "alpha"
        assert loaded[1].name == "bravo"
        assert loaded[1].provider == "codex"

    def test_load_workers_empty_file(self, isolated_config):
        save_workers("demo", [])
        loaded = load_workers("demo")
        assert loaded == []

    def test_load_team_not_found(self, isolated_config):
        with pytest.raises(FileNotFoundError, match="not found"):
            load_team("nonexistent")

    def test_load_workers_invalid_toml(self, isolated_config):
        cfg = isolated_config
        workers_path = cfg["state_dir"] / "demo" / "workers.toml"
        workers_path.parent.mkdir(parents=True, exist_ok=True)
        workers_path.write_text("workers = [\n")

        with pytest.raises(StateFileError, match="Could not parse"):
            load_workers("demo")

    def test_save_workers_strips_none(self, isolated_config):
        workers = [WorkerState(name="alpha", task="fix bug", session_id=None)]
        save_workers("demo", workers)
        cfg = isolated_config
        content = (cfg["state_dir"] / "demo" / "workers.toml").read_text()
        assert "session_id" not in content


class TestActiveTeam:
    def test_set_and_get_active_team(self, isolated_config):
        set_active_team("demo")
        assert get_active_team_name() == "demo"

    def test_no_active_team(self, isolated_config):
        assert get_active_team_name() is None

    def test_clear_active_team(self, isolated_config):
        set_active_team("demo")
        clear_active_team()
        assert get_active_team_name() is None

    def test_get_active_team_raises(self, isolated_config):
        with pytest.raises(RuntimeError, match="No active team"):
            get_active_team()


class TestLogging:
    def test_create_session_log_dir(self, isolated_config):
        cfg = isolated_config
        session_dir = create_session_log_dir("demo")
        assert session_dir.exists()
        current = cfg["logs_dir"] / "demo" / "current"
        assert current.is_symlink()
        assert current.resolve() == session_dir

    def test_current_session_log_dir(self, isolated_config):
        session_dir = create_session_log_dir("demo")
        result = current_session_log_dir("demo")
        assert result == session_dir

    def test_atomic_write_creates_parents(self, isolated_config):
        cfg = isolated_config
        deep_path = cfg["root"] / "a" / "b" / "c" / "file.txt"
        _atomic_write_bytes(deep_path, b"hello", "test file")
        assert deep_path.read_bytes() == b"hello"
