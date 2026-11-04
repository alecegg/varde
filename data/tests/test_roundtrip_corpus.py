from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from varde_core.frontmatter import parse
from varde_data.backends.sqlite.plan_state import SQLitePlanState
from varde_data.plan_state_sync import export_plan_dir, import_plan_dir
from varde_data.queue_md import parse_queue_md
from varde_data.queue_sync import (
    export_queue_md,
    import_queue_md,
    record_queue_md_export,
)

CORPUS = Path(__file__).parent / "fixtures" / "plan_corpus" / "plans"
_STATE_LINE = re.compile(
    rb"^(?:status|status_at|owner|assigned_to|merge_approved_at):.*(?:\n|$)",
    re.MULTILINE,
)
_PLAN_STATE_FIELDS = (
    "status",
    "status_at",
    "owner",
    "assigned_to",
    "merge_approved_at",
)
_TASK_STATE_FIELDS = ("status", "status_at")


def _state_fields(path: Path) -> dict[str, object]:
    fields, _ = parse(path.read_bytes().replace(b"\r\n", b"\n"))
    keys = _TASK_STATE_FIELDS if path.parent.name == "tasks" else _PLAN_STATE_FIELDS
    return {key: fields.get(key) for key in keys}


def _assert_state_fields(path: Path, expected: dict[str, object]) -> None:
    assert _state_fields(path) == expected


def _assert_table_bytes(actual: str, expected: str) -> None:
    assert actual == expected


def test_plan_task_and_table_queue_corpus_round_trips(tmp_path, monkeypatch) -> None:
    working = tmp_path / "working"
    plans = working / "plans"
    shutil.copytree(CORPUS, plans)
    monkeypatch.chdir(tmp_path)
    state = SQLitePlanState(working / ".cache" / "data" / "queue.sqlite3")

    plan_files = sorted(plans.glob("*/plan.md"))
    task_files = sorted(plans.glob("*/tasks/*.md"))
    assert {"completed", "building", "blocked", "cancelled", "todo"} <= {
        _frontmatter_status(path) for path in plan_files
    }
    expected_task_statuses = {
        "todo",
        "building",
        "in_review",
        "done",
        "blocked",
        "cancelled",
        "merged",
    }
    assert expected_task_statuses <= {_frontmatter_status(path) for path in task_files}

    originals = {path: path.read_bytes() for path in [*plan_files, *task_files]}
    expected_state = {path: _state_fields(path) for path in originals}
    for plan_file in plan_files:
        import_plan_dir(state.path.parents[2], plan_file.parent)
    for plan_file in plan_files:
        export_plan_dir(state.path.parents[2], plan_file.parent)
    for path, original in originals.items():
        _assert_state_fields(path, expected_state[path])
        assert _STATE_LINE.sub(b"", path.read_bytes()) == _STATE_LINE.sub(b"", original)

    baseline = {path: path.read_bytes() for path in originals}
    expected_state = {path: _state_fields(path) for path in originals}
    changed_plan = plan_files[0]
    changed_task = min(changed_plan.parent.glob("tasks/*.md"))
    state.set_plan_state(str(changed_plan.parent), status="exported-state")
    changed_task_state = state.set_task_state(
        str(changed_plan.parent), changed_task.stem, "exported-task-state", actor="test"
    )
    expected_state[changed_plan] = {
        **expected_state[changed_plan],
        "status": "exported-state",
    }
    expected_state[changed_task] = {
        **expected_state[changed_task],
        "status": "exported-task-state",
        "status_at": changed_task_state.status_at,
    }
    export_plan_dir(state.path.parents[2], changed_plan.parent)
    for path in originals:
        after = path.read_bytes()
        _assert_state_fields(path, expected_state[path])
        assert _STATE_LINE.sub(b"", after) == _STATE_LINE.sub(b"", baseline[path])

    queue_file = plans / "active" / "queue.md"
    queue_source = queue_file.read_text(encoding="utf-8")
    report = import_queue_md(queue_file, "anonymized-table")
    assert report.added > 0
    rendered = export_queue_md(working, "anonymized-table")
    _assert_table_bytes(rendered, queue_source)
    assert [row.values for row in parse_queue_md(rendered).rows] == [
        row.values for row in parse_queue_md(queue_source).rows
    ]
    queue_file.write_text(rendered, encoding="utf-8")
    record_queue_md_export(working, "anonymized-table", rendered)
    assert import_queue_md(queue_file, "anonymized-table").unchanged == report.added


def test_state_assertion_detects_corrupted_state_field(tmp_path: Path) -> None:
    plan_file = tmp_path / "plan.md"
    plan_file.write_bytes((CORPUS / "active" / "plan.md").read_bytes())
    expected = _state_fields(plan_file)
    plan_file.write_bytes(
        plan_file.read_bytes().replace(b"status: building", b"status: todo")
    )

    with pytest.raises(AssertionError):
        _assert_state_fields(plan_file, expected)


def test_table_assertion_detects_dropped_trailing_text() -> None:
    source = (CORPUS / "active" / "queue.md").read_text(encoding="utf-8")
    corrupted = source.replace("<!-- Anonymized trailing queue note. -->\n", "")

    with pytest.raises(AssertionError):
        _assert_table_bytes(corrupted, source)


def _frontmatter_status(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]
    for line in frontmatter.splitlines():
        if line.startswith("status:"):
            return line.partition(":")[2].strip().strip('"')
    raise AssertionError(f"status missing from {path}")
