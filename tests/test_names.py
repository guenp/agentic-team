"""Tests for agent name generation from task descriptions."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent / "src"))

from agentic_team.names import _FALLBACK_NAMES, match_name, name_from_task, next_fallback


class TestNameFromTask:
    def test_name_from_simple_task(self):
        result = name_from_task("Fix the login bug", [])
        assert result == "fix-login"

    def test_name_strips_stop_words(self):
        # "the" and "to" are stop words; "add" is meaningful
        result = name_from_task("Add the new feature to the API", [])
        assert result == "add-new"

    def test_name_deduplicates(self):
        result = name_from_task("fix auth", ["fix-auth"])
        assert result == "fix-auth-2"

    def test_name_deduplicates_chain(self):
        result = name_from_task("fix auth", ["fix-auth", "fix-auth-2"])
        assert result == "fix-auth-3"

    def test_name_fallback_on_all_stop_words(self):
        result = name_from_task("do it", [])
        assert result == "alpha"

    def test_name_fallback_skips_used(self):
        result = name_from_task("do it", ["alpha"])
        assert result == "bravo"

    def test_next_fallback_exhaustion(self):
        all_used = list(_FALLBACK_NAMES)
        with pytest.raises(RuntimeError, match="exhausted"):
            next_fallback(all_used)


class TestMatchName:
    def test_match_name_prefix(self):
        result = match_name("fix", ["fix-auth", "add-tests"])
        assert result == "fix-auth"

    def test_match_name_no_match(self):
        result = match_name("zz", ["fix-auth"])
        assert result is None

    def test_match_name_case_insensitive(self):
        result = match_name("FIX", ["fix-auth"])
        assert result == "fix-auth"
