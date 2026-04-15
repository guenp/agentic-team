"""Tests for markdown task file parsing and writeback."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent / "src"))

from agentic_team.taskfile import (
    TaskEntry,
    TaskFileError,
    parse_task_file,
    pending_tasks,
    update_task_file,
)


class TestParsing:
    def test_parse_unchecked_task(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("- [ ] Fix bug\n")
        tasks = parse_task_file(f)
        assert len(tasks) == 1
        assert tasks[0].task == "Fix bug"
        assert tasks[0].done is False

    def test_parse_checked_task(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("- [x] Fix bug\n")
        tasks = parse_task_file(f)
        assert len(tasks) == 1
        assert tasks[0].done is True

    def test_parse_heading_sets_workdir(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("## /repos/backend\n- [ ] Fix bug\n")
        tasks = parse_task_file(f)
        assert tasks[0].working_dir == "/repos/backend"

    def test_parse_tilde_expansion(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("## ~/repos\n- [ ] Fix bug\n")
        tasks = parse_task_file(f)
        assert tasks[0].working_dir is not None
        assert not tasks[0].working_dir.startswith("~")
        assert "repos" in tasks[0].working_dir

    def test_parse_inline_overrides(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("- [ ] Fix bug (provider: codex, mode: interactive)\n")
        tasks = parse_task_file(f)
        assert tasks[0].provider == "codex"
        assert tasks[0].mode == "interactive"
        assert tasks[0].task == "Fix bug"

    def test_parse_model_override(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("- [ ] Fix bug (model: o4-mini)\n")
        tasks = parse_task_file(f)
        assert tasks[0].model == "o4-mini"

    def test_parse_name_override(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("- [ ] Fix bug (name: my-worker)\n")
        tasks = parse_task_file(f)
        assert tasks[0].name == "my-worker"

    def test_parse_strips_annotation(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("- [ ] Fix bug \u2190 worker-1 | done | 2m\n")
        tasks = parse_task_file(f)
        assert tasks[0].task == "Fix bug"

    def test_parse_extracts_worker_name_from_annotation(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("- [ ] Fix bug \u2190 worker-1 | done | 2m\n")
        tasks = parse_task_file(f)
        assert tasks[0].worker_name == "worker-1"

    def test_parse_mixed_file(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text(
            "## /repos/backend\n"
            "- [ ] Fix bug\n"
            "- [x] Already done\n"
            "- [ ] Add tests (provider: codex)\n"
            "\n"
            "## /repos/frontend\n"
            "- [ ] Fix UI \u2190 ui-worker | running | 0m 30s\n"
        )
        tasks = parse_task_file(f)
        assert len(tasks) == 4
        assert tasks[0].working_dir == "/repos/backend"
        assert tasks[0].done is False
        assert tasks[1].done is True
        assert tasks[2].provider == "codex"
        assert tasks[3].working_dir == "/repos/frontend"
        assert tasks[3].worker_name == "ui-worker"

    def test_parse_preserves_line_numbers(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("# Header\n\n- [ ] First\n- [ ] Second\n")
        tasks = parse_task_file(f)
        assert tasks[0].line_number == 2
        assert tasks[1].line_number == 3

    def test_parse_preserves_indent(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("  - [ ] Indented task\n")
        tasks = parse_task_file(f)
        assert tasks[0].indent == "  "

    def test_pending_tasks_filters(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("- [ ] Pending\n- [x] Done\n- [ ] Also pending\n")
        result = pending_tasks(f)
        assert len(result) == 2
        assert all(not t.done for t in result)

    def test_parse_missing_file_raises(self, tmp_path):
        missing = tmp_path / "missing.md"
        with pytest.raises(TaskFileError, match="Could not read"):
            parse_task_file(missing)


class TestWriteback:
    def test_update_ticks_checkbox(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("- [ ] Fix bug\n- [ ] Add tests\n")
        entry = TaskEntry(task="Fix bug", done=True, line_number=0)
        update_task_file(f, {0: entry})
        lines = f.read_text().splitlines()
        assert lines[0].startswith("- [x]")
        assert lines[1].startswith("- [ ]")

    def test_update_appends_annotation(self, tmp_path):
        f = tmp_path / "tasks.md"
        f.write_text("- [ ] Fix bug \u2190 old-worker | running | 0m 05s\n")
        entry = TaskEntry(
            task="Fix bug",
            done=True,
            line_number=0,
            worker_name="worker-1",
            worker_status="done",
            elapsed="2m 30s",
        )
        update_task_file(f, {0: entry})
        content = f.read_text()
        assert "- [x] Fix bug \u2190 worker-1 | done | 2m 30s" in content
        # Old annotation replaced
        assert "old-worker" not in content
