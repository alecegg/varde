import ast
import contextlib
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from varde_data.records.plans import PlanRecord, TaskRecord
from varde_data.views import (
    Binding,
    StatusFacts,
    awaiting_user_message,
    classify_status,
    count_open_questions,
    dependency_order,
    json_merge_state,
    merge_verdict,
    now_line,
    parse_status_at,
    path_sort_key,
    plan_progress,
    section_bullets,
    section_span,
    stalled_detail,
    stalled_minutes,
    task_progress,
)
from varde_data.views.status import BACKLOG, TASK_ACTIVE, TERMINAL


def _task(identifier: str, status: str, **fields: object) -> TaskRecord:
    return TaskRecord(
        id=identifier,
        fields={"status": status, **fields},
        raw=b"",
        mtime=0,
        path=f"tasks/{identifier}.md",
    )


def _plan(identifier: str, depends_on: list[str] | None = None) -> PlanRecord:
    return PlanRecord(
        id=identifier,
        fields={"depends_on": depends_on or []},
        raw=b"",
        mtime=0,
        path=f"plans/{identifier}/plan.md",
    )


def _progress_record(
    identifier: str,
    path: str,
    **updates: object,
) -> dict[str, object]:
    record: dict[str, object] = {
        "id": identifier,
        "path": path,
        "title": identifier,
        "label": identifier,
        "purpose": "",
        "status": "active",
        "group_name": "",
        "group": False,
        "depends": [],
        "done": 0,
        "total": 0,
        "in_progress": False,
        "questions": 0,
        "terminal": False,
        "now": None,
        "now_at": None,
        "merge": "none",
        "merge_state": "absent",
        "stalled": False,
        "owner": None,
    }
    record.update(updates)
    return record


def test_classifies_status_and_stall_elapsed_time() -> None:
    assert classify_status("completed") == "terminal"
    assert classify_status("backlog") == "backlog"
    assert classify_status("in_progress") == "other"
    assert stalled_minutes(1_000, 880, 2) == 2
    assert stalled_minutes(1_000, 1_100, 1) is None


def test_question_count_ignores_nested_and_fenced_bullets() -> None:
    assert (
        count_open_questions(
            "## Open Questions\n- First\n  continuation\n- Second\n"
            "```md\n- Example\n## Hidden\n```\n## Next\n- Excluded"
        )
        == 2
    )


def test_task_progress_uses_in_memory_facts_and_records() -> None:
    plan = PlanRecord(
        id="plan",
        fields={},
        raw=b"",
        mtime=0,
        path="plans/plan.md",
        tasks=(
            _task("done", "completed"),
            _task(
                "active",
                "in_progress",
                title="Build",
                status_at="1970-01-01T00:00:00+00:00",
            ),
        ),
    )
    result = task_progress(
        plan,
        StatusFacts(
            clock=601, stall_minutes=10, bindings=(Binding("address", "plan"),)
        ),
    )
    assert result == {
        "done": 1,
        "total": 2,
        "in_progress": True,
        "now": "Build stalled 10m",
    }


def test_task_title_defaults_to_task_file_stem() -> None:
    task = TaskRecord(
        id="frontmatter-id",
        fields={"status": "in_progress"},
        raw=b"",
        mtime=0,
        path="tasks/file-stem.md",
    )
    result = task_progress(
        PlanRecord("plan", {}, b"", 0, "plan.md", (task,)),
        StatusFacts(clock=0),
    )
    assert result["now"] == "file-stem in progress"


def test_dependency_order_and_dated_path_order() -> None:
    first, second = _plan("a"), _plan("b", ["a"])
    assert dependency_order([second, first]) == [first, second]
    assert path_sort_key("2025-01-02-later") > path_sort_key("2024-01-02-earlier")


def test_plan_rollup_groups_counts_hides_backlog_and_orders_current_work() -> None:
    records = {
        "2025-01-01-group": {
            "id": "2025-01-01-group",
            "path": "plans/2025-01-01-group/plan.md",
            "title": "Group",
            "label": "Group",
            "status": "active",
            "group": True,
            "group_name": "",
            "depends": [],
            "done": 0,
            "total": 0,
            "in_progress": False,
            "terminal": False,
            "now": None,
            "now_at": None,
            "merge": "none",
            "merge_state": "absent",
            "stalled": False,
            "owner": None,
            "questions": 0,
        },
        "2025-01-02-child": {
            "id": "2025-01-02-child",
            "path": "plans/2025-01-02-child/plan.md",
            "title": "Child",
            "label": "Child",
            "status": "active",
            "group": False,
            "group_name": "",
            "depends": [],
            "done": 2,
            "total": 2,
            "in_progress": True,
            "terminal": False,
            "now": "Build — now",
            "now_at": None,
            "merge": "none",
            "merge_state": "absent",
            "stalled": False,
            "owner": None,
            "questions": 0,
        },
        "2025-01-03-backlog": {
            "id": "2025-01-03-backlog",
            "path": "plans/2025-01-03-backlog/plan.md",
            "title": "Later",
            "label": "Later",
            "status": "backlog",
            "group": False,
            "group_name": "",
            "depends": [],
            "done": 0,
            "total": 0,
            "in_progress": False,
            "terminal": False,
            "now": None,
            "now_at": None,
            "merge": "none",
            "merge_state": "absent",
            "stalled": False,
            "owner": None,
            "questions": 0,
        },
    }
    result: Any = plan_progress(
        records,
        {"2025-01-01-group": ["2025-01-02-child"]},
        list(records),
    )
    assert result["backlog_count"] == 1
    assert result["more_count"] == 0
    group = result["plans"][0]
    assert (group["done"], group["total"], group["unit"]) == (0, 1, "plans")
    assert group["children"][0]["now"] == "Build - now"


def test_plan_progress_uses_record_paths_for_dated_order_and_ties() -> None:
    records = {
        "late": _progress_record("late", "plans/z/2025-01-01-shared/plan.md"),
        "early": _progress_record("early", "plans/2024-01-01-first/plan.md"),
        "tie": _progress_record("tie", "plans/a/2025-01-01-shared/plan.md"),
    }
    result: Any = plan_progress(records, {}, ["late", "early", "tie"])
    assert [plan["id"] for plan in result["plans"]] == ["early", "tie", "late"]


def test_plan_progress_keeps_draft_roots_out_of_collapsed_backlog() -> None:
    records = {
        "example-draft": _progress_record(
            "example-draft", "plans/example-draft/plan.md", status="backlog"
        )
    }
    result: Any = plan_progress(records, {}, ["example-draft"])
    assert result["backlog_count"] == 0
    assert [plan["id"] for plan in result["plans"]] == ["example-draft"]


def test_plan_progress_prioritizes_active_work_then_task_activity() -> None:
    records = {
        "empty": _progress_record("empty", "plans/m-empty/plan.md"),
        "tasks": _progress_record("tasks", "plans/a-tasks/plan.md", total=2),
        "active": _progress_record(
            "active", "plans/z-active/plan.md", total=1, in_progress=True
        ),
    }
    result: Any = plan_progress(records, {}, ["empty", "tasks", "active"])
    assert [plan["id"] for plan in result["plans"]] == ["active", "tasks", "empty"]


def test_plan_progress_shows_waits_on_for_non_completed_dependency() -> None:
    records = {
        "plan": _progress_record(
            "plan", "plans/2025-01-01-plan/plan.md", depends=["dependency"]
        ),
        "dependency": _progress_record(
            "dependency", "plans/2024-01-01-dependency/plan.md", status="ready"
        ),
    }
    result: Any = plan_progress(records, {}, ["plan", "dependency"])
    by_id = {plan["id"]: plan for plan in result["plans"]}
    assert by_id["plan"]["now"] == "waits on dependency"


def test_merge_nowline_awaiting_and_stall_views_consume_status_facts() -> None:
    facts = StatusFacts(
        clock=1_300,
        branches={"worktree/p": 500},
        merged=frozenset({"worktree/p"}),
        now_lines={"p": "working"},
        now_line_timestamps={"p": 900},
        bindings=(Binding("agent", "p", last_seen="1970-01-01T00:10:00+00:00"),),
    )
    assert json_merge_state({"id": "p", "merge_approved_at": "now"}, facts) == "merged"
    assert now_line("p", facts) == (
        "working",
        datetime.fromtimestamp(900).astimezone().isoformat(),
    )
    record = {"id": "p", "assigned_to": "agent", "status": "active"}
    request = {"from": "agent", "to": "main", "kind": "needs-user", "text": "question"}
    assert awaiting_user_message(record, [request]) == request
    assert (
        awaiting_user_message(record, [request, {"from": "main", "to": "agent"}])
        is None
    )
    assert (
        stalled_detail(record, [{"status": "todo"}], [], facts)
        == "stalled; idle 11m with open work and no hand-back"
    )
    owner_message = {"from": "p", "ts": "1970-01-01T00:12:00Z"}
    assert stalled_detail(record, [{"status": "todo"}], [owner_message], facts) is None


def test_awaiting_user_message_clears_dashboard_response_and_skips_terminal() -> None:
    request = {"from": "agent", "to": "main", "kind": "needs-user"}
    dashboard_response = {"from": "dashboard", "to": "agent"}
    assigned = {"id": "p", "assigned_to": "agent", "status": "active"}
    assert awaiting_user_message(assigned, [request, dashboard_response]) is None
    terminal = {**assigned, "status": "completed"}
    assert awaiting_user_message(terminal, [request]) is None


def test_merge_classification_uses_review_verdict_and_completed_status() -> None:
    assert merge_verdict(None, "completed") == "none"
    assert merge_verdict("approved", "active") == "ready"
    assert merge_verdict("approved", "completed") == "merged"


def test_status_facts_defaults_are_immutable_and_hashable() -> None:
    facts = StatusFacts(clock=0)
    assert isinstance(hash(facts), int)
    with pytest.raises(TypeError):
        facts.now_lines["plan"] = "change"  # type: ignore[index]
    source = {"plan": "original"}
    copied = StatusFacts(clock=0, now_lines=source)
    source["plan"] = "changed"
    assert copied.now_lines["plan"] == "original"


def test_public_status_parsing_helpers() -> None:
    assert parse_status_at("bad") is None
    body = "## Open Questions\n- One\n## Next\n- Other"
    span = section_span(body, "open questions")
    assert span is not None
    lines: list[str] = [str(line) for line in body.splitlines()]
    assert section_bullets(lines, *span) == [(1, 2, "One")]


def test_json_merge_state_distinguishes_missing_and_unmerged_branches() -> None:
    facts = StatusFacts(clock=0, branches={"topic": 10})
    record = {"id": "p", "merge_approved_at": "now", "branch": "topic"}
    assert json_merge_state({"id": "p"}, facts) == "absent"
    assert json_merge_state({**record, "branch": "missing"}, facts) == "unknown"
    assert json_merge_state(record, facts) == "approved_not_merged"


def test_stalled_detail_obeys_ten_minute_boundary() -> None:
    record = {"id": "p", "assigned_to": "agent", "status": "active"}
    task: list[Mapping[str, object]] = [{"status": "todo"}]
    at_nine = StatusFacts(
        clock=1_199,
        bindings=(Binding("agent", last_seen="1970-01-01T00:10:00+00:00"),),
    )
    at_ten = StatusFacts(
        clock=1_200,
        bindings=(Binding("agent", last_seen="1970-01-01T00:10:00+00:00"),),
    )
    assert stalled_detail(record, task, [], at_nine) is None
    assert stalled_detail(record, task, [], at_ten) == (
        "stalled; idle 10m with open work and no hand-back"
    )


def test_status_sets_match_view_definitions() -> None:
    status_tree = _status_tree()
    assert frozenset(_constant(status_tree, "TERMINAL")) == TERMINAL
    assert frozenset(_constant(status_tree, "BACKLOG")) == BACKLOG
    for state in TASK_ACTIVE:
        assert (
            task_progress(
                PlanRecord(
                    id="plan",
                    fields={},
                    raw=b"",
                    mtime=0,
                    path="plan.md",
                    tasks=(_task("active", state),),
                ),
                StatusFacts(clock=0),
            )["in_progress"]
            is True
        )


@pytest.mark.parametrize(
    ("status_at", "mtime", "note_mtime", "expected"),
    [
        ("", 9_000, None, "Active stalled 16m"),
        ("bad", 9_000, None, "Active stalled 16m"),
        ("1970-01-01T02:46:40+00:00", 9_000, 9_500, "Active in progress"),
        ("1970-01-01T02:30:00+00:00", 9_000, 8_000, "Active stalled 16m"),
        ("1970-01-01T02:46:40+00:00", 9_000, 9_000, "Active in progress"),
    ],
)
def test_task_rollup_matches_workflow_read_tasks(
    tmp_path,
    status_at: str,
    mtime: float,
    note_mtime: float | None,
    expected: str,
) -> None:
    """Keep ready/next/active/stall rules aligned until the workflow adapter moves."""
    import os

    plan_path = tmp_path / "plan.md"
    plan_path.write_text("", encoding="utf-8")
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    definitions = [
        ("01-done", "completed", []),
        ("02-dependent", "todo", ["01-done"]),
        ("03-active", "in_progress", []),
    ]
    records = []
    for stem, state, dependencies in definitions:
        path = tasks_dir / f"{stem}.md"
        timestamp = status_at if stem == "03-active" else ""
        title = "Active" if stem == "03-active" else stem
        path.write_text(
            f"---\nartifact_type: task\nstatus: {state}\n"
            f"depends_on: {dependencies!r}\ntitle: {title}\n"
            f"status_at: {timestamp!r}\n---\n",
            encoding="utf-8",
        )
        task_mtime = mtime if stem == "03-active" else 9_900
        os.utime(path, (task_mtime, task_mtime))
        fields = {
            "artifact_type": "task",
            "status": state,
            "depends_on": dependencies,
            "title": "Active" if stem == "03-active" else stem,
            "status_at": timestamp,
        }
        records.append(TaskRecord(stem, fields, b"", path.stat().st_mtime, str(path)))
    if note_mtime is not None:
        note_path = tmp_path / "notes" / "03-active.md"
        note_path.parent.mkdir()
        note_path.write_text("note", encoding="utf-8")
        os.utime(note_path, (note_mtime, note_mtime))
    fields_by_path = {}
    for record in records:
        fields_by_path[Path(record.path)] = record.fields
    workflow_read_tasks = _workflow_read_tasks(fields_by_path, clock=10_000)
    old_result, skipped = workflow_read_tasks(plan_path, 10)
    view_result = task_progress(
        PlanRecord("plan", {}, b"", 0, str(plan_path), tuple(records)),
        StatusFacts(
            clock=10_000,
            stall_minutes=10,
            task_activity={"03-active": note_mtime} if note_mtime is not None else {},
        ),
    )
    assert skipped == 0
    assert old_result == view_result
    assert view_result["now"] == expected


@pytest.mark.parametrize(
    ("dependencies", "expected"),
    [
        (["02-source"], "next: 02-source"),
        (["02-source", "01-waiting"], "next: 01-waiting"),
    ],
)
def test_ready_and_fallback_next_match_workflow(
    tmp_path: Path, dependencies: list[str], expected: str
) -> None:
    plan_path = tmp_path / "plan.md"
    plan_path.touch()
    task_dir = tmp_path / "tasks"
    task_dir.mkdir()
    task_specs = [
        ("01-waiting", dependencies),
        ("02-source", ["01-waiting"] if len(dependencies) > 1 else []),
    ]
    records = []
    fields_by_path = {}
    for stem, depends_on in task_specs:
        path = task_dir / f"{stem}.md"
        path.touch()
        fields = {
            "artifact_type": "task",
            "status": "todo",
            "title": stem,
            "depends_on": depends_on,
        }
        fields_by_path[path] = fields
        records.append(TaskRecord(stem, fields, b"", 0, str(path)))
    facts = StatusFacts(clock=0)
    result = task_progress(
        PlanRecord("plan", {}, b"", 0, str(plan_path), tuple(records)), facts
    )
    oracle, _ = _workflow_read_tasks(fields_by_path, clock=0)(plan_path, 10)
    assert result == oracle
    assert result["now"] == expected


def _status_tree() -> ast.Module:
    root = Path(__file__).parents[3]
    status_path = root / "data/src/varde_data/views/status.py"
    return ast.parse(status_path.read_text(encoding="utf-8"))


def _constant(tree: ast.Module, name: str) -> Any:
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        )
    )
    value = assignment.value
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "frozenset"
        and value.args
    ):
        return frozenset(ast.literal_eval(value.args[0]))
    return ast.literal_eval(value)


def _workflow_read_tasks(fields_by_path: dict[Path, dict[str, object]], clock: float):
    active_states = set(TASK_ACTIVE)

    def read_tasks(plan_path: Path, stall_threshold: int):
        task_paths = sorted(plan_path.parent.joinpath("tasks").iterdir())
        records = []
        for path in task_paths:
            if path.suffix != ".md" or not path.is_file():
                continue
            fields = fields_by_path[path]
            if fields.get("artifact_type", fields.get("type", "plan")) != "task":
                continue
            status = fields.get("status", "todo")
            dependencies = fields.get("depends_on", [])
            if isinstance(dependencies, str):
                dependencies = [dependencies]
            records.append(
                {
                    "id": fields.get("id", path.stem),
                    "stem": path.stem,
                    "title": fields.get("title", path.stem),
                    "status": status,
                    "status_at": fields.get("status_at"),
                    "depends": dependencies,
                    "path": path,
                }
            )
        done = sum(
            classify_status(record["status"]) == "terminal" for record in records
        )
        active = next(
            (record for record in records if record["status"] in active_states), None
        )
        ready = next(
            (
                record
                for record in records
                if classify_status(record["status"]) != "terminal"
                and record["status"] not in active_states
                and all(
                    all(
                        classify_status(candidate["status"]) == "terminal"
                        for candidate in records
                        if candidate["stem"] == dependency
                        or candidate["id"] == dependency
                    )
                    for dependency in record["depends"]
                )
            ),
            None,
        )
        next_task = ready or next(
            (
                record
                for record in records
                if classify_status(record["status"]) != "terminal"
                and record["status"] not in active_states
            ),
            None,
        )
        current = (
            f"{active['title']} {active['status'].replace('_', ' ')}"
            if active
            else f"next: {next_task['title']}"
            if next_task
            else None
        )
        if active:
            activity = active["path"].stat().st_mtime
            status_at = active["status_at"]
            if isinstance(status_at, str):
                with contextlib.suppress(ValueError):
                    activity = datetime.fromisoformat(status_at).timestamp()
            note_path = plan_path.parent / "notes" / f"{active['id']}.md"
            if note_path.exists():
                activity = max(activity, note_path.stat().st_mtime)
            elapsed = max(0, int((clock - activity) // 60))
            if elapsed >= stall_threshold and current is not None:
                current = current.replace(
                    f" {active['status'].replace('_', ' ')}", f" stalled {elapsed}m"
                )
        return {
            "done": done,
            "total": len(records),
            "in_progress": active is not None,
            "now": current,
        }, 0

    return read_tasks
