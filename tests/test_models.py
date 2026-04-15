"""Tests for provider registry, flag generation, and health checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent / "src"))

from agentic_team.models import (
    PROVIDERS,
    describe_provider_flags,
    get_provider,
    get_provider_health,
)


class TestProviderLookup:
    def test_get_provider_known(self):
        p = get_provider("claude")
        assert p.cli_command == "claude"
        assert p.name == "claude"

    def test_get_provider_unknown(self):
        with pytest.raises(KeyError, match="Unknown provider"):
            get_provider("unknown")

    def test_all_providers_have_ready_indicators(self):
        for name, prov in PROVIDERS.items():
            assert len(prov.ready_indicators) > 0, f"{name} missing ready_indicators"


class TestFlagGeneration:
    def test_claude_interactive_flags(self):
        flags = describe_provider_flags("claude", mode="interactive")
        assert "--permission-mode" in flags
        assert "auto" in flags
        assert "--print" not in flags

    def test_claude_oneshot_flags(self):
        flags = describe_provider_flags("claude", mode="oneshot")
        assert "--print" in flags
        assert "--output-format" in flags
        assert "stream-json" in flags
        assert "--permission-mode" in flags

    def test_claude_with_model(self):
        flags = describe_provider_flags("claude", model="opus")
        assert "--model" in flags
        assert "opus" in flags

    def test_codex_interactive_flags(self):
        flags = describe_provider_flags("codex", mode="interactive")
        assert "--full-auto" in flags
        assert "--permission-mode" not in flags

    def test_codex_oneshot_flags(self):
        flags = describe_provider_flags("codex", mode="oneshot")
        assert "--full-auto" in flags
        assert "--quiet" in flags

    def test_gemini_interactive_flags(self):
        flags = describe_provider_flags("gemini", mode="interactive")
        assert "--yolo" in flags

    def test_gemini_oneshot_flags(self):
        flags = describe_provider_flags("gemini", mode="oneshot")
        assert "--yolo" in flags
        assert "--prompt" in flags


class TestProviderHealth:
    def test_health_not_installed(self):
        with patch("shutil.which", return_value=None):
            health = get_provider_health("claude")
        assert health.installed is False
        assert health.viable is False

    def test_claude_auth_success(self):
        auth_json = json.dumps({"loggedIn": True, "authMethod": "api_key", "email": "user@test.com"})
        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch(
                "agentic_team.models._run_status_command",
                return_value=subprocess.CompletedProcess([], 0, auth_json, ""),
            ),
        ):
            health = get_provider_health("claude")
        assert health.installed is True
        assert health.authenticated is True

    def test_claude_auth_failure(self):
        auth_json = json.dumps({"loggedIn": False})
        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch(
                "agentic_team.models._run_status_command",
                return_value=subprocess.CompletedProcess([], 0, auth_json, ""),
            ),
        ):
            health = get_provider_health("claude")
        assert health.installed is True
        assert health.authenticated is False

    def test_gemini_auth_env_var(self):
        with (
            patch("shutil.which", return_value="/usr/bin/gemini"),
            patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}, clear=False),
        ):
            health = get_provider_health("gemini")
        assert health.installed is True
        assert health.authenticated is True
