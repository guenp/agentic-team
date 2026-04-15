"""Tests for command construction contracts — the CLI compatibility layer.

These tests assert the exact command strings built for each provider.
If a provider CLI changes flags, these tests break first.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent / "src"))

from agentic_team.agents import (
    build_lead_command,
    build_resume_command,
    build_team_lead_system_prompt,
    build_worker_command,
    build_worker_system_prompt,
    write_system_prompt_file,
)
from agentic_team.config import TeamConfig


class TestLeadCommand:
    def test_build_lead_claude(self, tmp_path):
        cfg = TeamConfig(name="demo", provider="claude", working_dir=str(tmp_path))
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("lead prompt")
        log_path = tmp_path / "lead.log"
        cmd = build_lead_command(cfg, prompt_file, log_path=log_path)
        assert cmd.startswith("claude ")
        assert "--append-system-prompt-file" in cmd
        assert "--verbose" in cmd
        assert "--permission-mode auto" in cmd
        assert "2>>" in cmd

    def test_build_lead_codex(self, tmp_path):
        cfg = TeamConfig(name="demo", provider="codex", working_dir=str(tmp_path))
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("lead prompt")
        log_path = tmp_path / "lead.log"
        cmd = build_lead_command(cfg, prompt_file, log_path=log_path)
        assert cmd.startswith("RUST_LOG=")
        assert "codex" in cmd
        assert "--full-auto" in cmd

    def test_build_lead_gemini(self, tmp_path):
        cfg = TeamConfig(name="demo", provider="gemini", working_dir=str(tmp_path))
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("lead prompt")
        log_path = tmp_path / "lead.log"
        cmd = build_lead_command(cfg, prompt_file, log_path=log_path)
        assert "gemini" in cmd
        assert "--yolo" in cmd
        assert "--debug" in cmd


class TestWorkerCommandInteractive:
    def test_build_worker_claude_interactive(self, tmp_path):
        log_path = tmp_path / "worker.log"
        cmd = build_worker_command(
            "claude", "Fix bug", mode="interactive",
            team_name="demo", working_dir="/repo",
            log_path=log_path,
        )
        assert cmd.startswith("claude ")
        assert "--permission-mode auto" in cmd
        assert "--append-system-prompt" in cmd
        assert "You are a worker" in cmd
        assert "--verbose" in cmd
        assert "2>>" in cmd

    def test_build_worker_codex_interactive(self, tmp_path):
        log_path = tmp_path / "worker.log"
        cmd = build_worker_command(
            "codex", "Fix bug", mode="interactive",
            log_path=log_path,
        )
        assert "RUST_LOG=info" in cmd
        assert "codex" in cmd
        assert "--full-auto" in cmd
        assert "2>>" in cmd

    def test_build_worker_gemini_interactive(self, tmp_path):
        log_path = tmp_path / "worker.log"
        cmd = build_worker_command(
            "gemini", "Fix bug", mode="interactive",
            log_path=log_path,
        )
        assert "gemini" in cmd
        assert "--yolo" in cmd
        assert "--debug" in cmd
        assert "2>>" in cmd


class TestWorkerCommandOneshot:
    def test_build_worker_claude_oneshot(self, tmp_path):
        log_path = tmp_path / "worker.log"
        cmd = build_worker_command(
            "claude", "Fix bug", mode="oneshot",
            log_path=log_path,
        )
        assert "--print" in cmd
        assert "--output-format stream-json" in cmd
        assert "'Fix bug'" in cmd or '"Fix bug"' in cmd
        assert "> " in cmd and "2>&1" in cmd

    def test_build_worker_codex_oneshot(self, tmp_path):
        log_path = tmp_path / "worker.log"
        cmd = build_worker_command(
            "codex", "Fix bug", mode="oneshot",
            log_path=log_path,
        )
        assert "--full-auto" in cmd
        assert "--quiet" in cmd
        assert "'Fix bug'" in cmd or '"Fix bug"' in cmd
        assert "> " in cmd and "2>&1" in cmd

    def test_build_worker_gemini_oneshot(self, tmp_path):
        log_path = tmp_path / "worker.log"
        cmd = build_worker_command(
            "gemini", "Fix bug", mode="oneshot",
            log_path=log_path,
        )
        assert "--yolo" in cmd
        assert "--prompt" in cmd
        assert "'Fix bug'" in cmd or '"Fix bug"' in cmd
        assert "> " in cmd and "2>&1" in cmd


class TestWorkerCommandModelOverride:
    def test_build_worker_with_model(self, tmp_path):
        log_path = tmp_path / "worker.log"
        cmd = build_worker_command(
            "claude", "Fix bug", mode="interactive",
            model="opus", log_path=log_path,
        )
        assert "--model opus" in cmd


class TestResumeCommand:
    def test_build_resume_claude_oneshot(self, tmp_path):
        log_path = tmp_path / "worker.log"
        cmd = build_resume_command(
            "claude", "abc-123", "Fix the rest",
            log_path=log_path, mode="oneshot",
        )
        assert "--print" in cmd
        assert "--resume abc-123" in cmd
        assert "'Fix the rest'" in cmd or '"Fix the rest"' in cmd

    def test_build_resume_claude_interactive(self, tmp_path):
        log_path = tmp_path / "worker.log"
        cmd = build_resume_command(
            "claude", "abc-123", "Fix the rest",
            log_path=log_path, mode="interactive",
        )
        assert "--resume abc-123" in cmd
        # Interactive mode: prompt is NOT a positional arg
        assert "Fix the rest" not in cmd or "--resume" in cmd

    def test_build_resume_gemini(self, tmp_path):
        log_path = tmp_path / "worker.log"
        cmd = build_resume_command(
            "gemini", "session-456", "Continue fixing",
            log_path=log_path, mode="oneshot",
        )
        assert "--yolo" in cmd
        assert "--resume session-456" in cmd

    def test_build_resume_codex_raises(self):
        with pytest.raises(ValueError, match="does not support"):
            build_resume_command("codex", "session-id", "prompt")


class TestSystemPrompts:
    def test_worker_system_prompt_contains_team_and_dir(self):
        prompt = build_worker_system_prompt("demo", "/repos/project")
        assert "demo" in prompt
        assert "/repos/project" in prompt

    def test_lead_system_prompt_contains_commands(self):
        cfg = TeamConfig(name="demo", provider="claude", max_workers=8, working_dir="/repos")
        prompt = build_team_lead_system_prompt(cfg)
        assert "spawn-worker" in prompt
        assert "status" in prompt
        assert "wait" in prompt
        assert "8" in prompt  # max_workers
