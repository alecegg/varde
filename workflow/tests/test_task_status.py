from __future__ import annotations

import re
from argparse import Namespace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from varde_data.errors import Conflict, Locked
from varde_workflow import cli, merge_approval
from varde_workflow.commands import approve_merge, assign, owner, plan_answer, status
from varde_workflow.commands.plan_write_errors import map_plan_write_error
from varde_workflow.commands.task_set import run as run_task_set
from varde_workflow.commands.validate import validate
from varde_workflow.merge_approval import Approval
from varde_workflow.schema import built_in, can_transition

ACTIVE = {"in_progress", "building", "in_review", "fixing", "integrating"}


def test_plan_writer_errors_have_retry_codes() -> None:
    conflict = map_plan_write_error(Conflict("plan content changed"))
    locked = map_plan_write_error(Locked("lock timed out"))

    assert conflict is not None
    assert (conflict.error_code(), str(conflict)) == (
        "plan_conflict",
        "plan changed while writing; reload it and retry",
    )
    assert locked is not None
    assert (locked.error_code(), str(locked)) == (
        "plan_locked",
        "plan is locked by another operation; retry shortly",
    )


@pytest.mark.parametrize("error_type", [Conflict, Locked])
@pytest.mark.parametrize(
    "command,writer_method",
    [
        ("owner", "set_owner"),
        ("task_set", "set_task_status"),
        ("assign", "set_assigned_to"),
        ("approve_merge", "set_merge_approved_at"),
        ("plan_answer", "replace_body"),
    ],
)
def test_plan_write_commands_report_conflict_and_locked(
    command: str,
    writer_method: str,
    error_type: type[Exception],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path / "working"))
    plan = tmp_path / "working" / "plans" / "demo" / "plan.md"
    tasks = plan.parent / "tasks"
    tasks.mkdir(parents=True)
    plan.write_text(
        "---\ntype: plan\nid: demo\nstatus: active\n---\n"
        "## Open Questions\n- What?\n\n## Decisions so far\n",
        encoding="utf-8",
    )
    task = tasks / "task.md"
    task.write_text("---\ntype: task\nstatus: todo\n---\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    def fail(*args, **kwargs):
        raise error_type("forced writer error")

    class FailingRepository:
        def get_by_path(self, path: str):
            return Namespace(raw=Path(path).read_bytes(), path=path)

        def __getattr__(self, name: str):
            if name == writer_method:
                return fail
            raise AttributeError(name)

    from varde_workflow.commands import plan_write_errors

    monkeypatch.setattr(
        plan_write_errors,
        "plan_repository",
        lambda *_args: FailingRepository(),
    )
    if command == "owner":
        result = owner.run(
            Namespace(
                plan="demo/plan.md",
                owner="claude:session",
                clear=False,
                json=False,
            )
        )
    elif command == "task_set":
        result = run_task_set(
            Namespace(task=str(task), plan=None, state="building", json=True)
        )
    elif command == "assign":
        result = assign.run(
            Namespace(plan="demo", slot="orchestrator-2", clear=False, json=True)
        )
    elif command == "approve_merge":
        monkeypatch.setattr(
            merge_approval,
            "fetch_approval",
            lambda _id, _reviewed: Approval("demo", "2026-01-01"),
        )
        result = approve_merge.run(Namespace(plan="demo/plan.md", json=True))
    else:
        result = plan_answer.run(
            Namespace(plan=str(plan), question="What?", answer="An answer", json=True)
        )

    captured = capsys.readouterr()
    expected_code = "plan_locked" if error_type is Locked else "plan_conflict"
    assert result == 1
    assert "forced writer error" not in captured.err
    assert "traceback" not in captured.err.lower()
    if command == "owner":
        expected_message = (
            "plan is locked by another operation; retry shortly"
            if error_type is Locked
            else "plan changed while writing; reload it and retry"
        )
        assert expected_message in captured.err
    else:
        assert f'"code":"{expected_code}"' in captured.err


def test_plan_answer_conflicts_with_edit_after_record_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path / "working"))
    plan = tmp_path / "working" / "plans" / "demo" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntype: plan\nid: demo\nstatus: active\n---\n"
        "## Open Questions\n- What?\n\n## Decisions so far\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    answer_question = plan_answer.answer_question

    def hand_edit_before_write(*args, **kwargs):
        updated = answer_question(*args, **kwargs)
        plan.write_bytes(plan.read_bytes() + b"\n## Hand edit\nPreserve me.\n")
        return updated

    monkeypatch.setattr(plan_answer, "answer_question", hand_edit_before_write)
    result = plan_answer.run(
        Namespace(plan=str(plan), question="What?", answer="An answer", json=True)
    )

    error = capsys.readouterr().err
    assert result == 1
    assert '"code":"plan_conflict"' in error
    assert "Preserve me." in plan.read_text(encoding="utf-8")


def test_plan_repository_uses_the_resolved_plans_root(tmp_path: Path) -> None:
    plan = tmp_path / "separate-tree" / "plans" / "sample" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\ntype: plan\nid: sample\n---\n", encoding="utf-8")
    cwd_working = tmp_path / "cwd" / "working"

    from varde_workflow.commands.plan_write_errors import plan_repository

    record = plan_repository(cwd_working, plan).get_by_path(str(plan))

    assert record.id == "sample"


def _task(path: Path, state: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntype: task\nstatus: {state}\ndepends_on: []\n---\n"
        "## Acceptance criteria\n- works\n",
        encoding="utf-8",
    )
    return path


def test_task_state_machine_transitions() -> None:
    machine = built_in().artifact_type("task")
    assert machine.states == ACTIVE | {"todo", "blocked", "done"}
    assert can_transition(machine, "todo", "building")
    assert can_transition(machine, "todo", "blocked")
    assert all(
        can_transition(machine, state, target)
        for state in ACTIVE
        for target in ACTIVE
        if state != target
    )
    assert all(not can_transition(machine, state, state) for state in ACTIVE)
    assert all(
        can_transition(machine, state, target)
        for state in ACTIVE
        for target in ("blocked", "done")
    )
    assert all(can_transition(machine, "blocked", state) for state in ACTIVE)
    assert not can_transition(machine, "done", "building")
    assert not can_transition(machine, "todo", "done")


def test_validate_accepts_all_task_states_and_rejects_unknown(tmp_path: Path) -> None:
    for state in ACTIVE | {"todo", "blocked", "done"}:
        artifact, errors, _ = validate(_task(tmp_path / f"{state}.md", state))
        assert artifact is not None
        assert errors == []

    artifact, errors, _ = validate(_task(tmp_path / "unknown.md", "mystery"))
    assert artifact is None
    assert any("not a legal task status" in item.message for item in errors)

    invalid_time = _task(tmp_path / "invalid-time.md", "todo")
    invalid_time.write_text(
        invalid_time.read_text().replace(
            "status: todo", "status: todo\nstatus_at: yesterday"
        )
    )
    artifact, errors, _ = validate(invalid_time)
    assert artifact is None
    assert any(
        "status_at" in item.field and "ISO timestamp" in item.message for item in errors
    )


def test_validate_accepts_high_task_risk_and_rejects_other_values(
    tmp_path: Path,
) -> None:
    task = _task(tmp_path / "high-risk.md", "todo")
    task.write_text(
        task.read_text().replace("status: todo", "status: todo\nrisk: high")
    )
    artifact, errors, _ = validate(task)
    assert artifact is not None
    assert errors == []

    task.write_text(task.read_text().replace("risk: high", "risk: medium"))
    artifact, errors, _ = validate(task)
    assert artifact is None
    assert any(
        item.field == "risk" and "must be `high`" in item.message for item in errors
    )


def test_task_set_writes_status_and_utc_status_at_and_done_is_terminal(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    task = _task(tmp_path / "tasks" / "one.md", "todo")

    assert cli.run(["task", "set", str(task), "building"]) == 0
    output = capsys.readouterr().out
    assert "building" in output
    text = task.read_text(encoding="utf-8")
    assert "status: building" in text
    match = re.search(
        r"^status_at: '?(\d{4}-\d\d-\d\dT[^'\n]+Z)'?$", text, re.MULTILINE
    )
    assert match

    assert cli.run(["task", "set", str(task), "in_review", "--json"]) == 0
    assert '"status":"in_review"' in capsys.readouterr().out

    assert cli.run(["task", "set", str(task), "done"]) == 0
    capsys.readouterr()
    assert cli.run(["task", "set", str(task), "fixing"]) == 1
    assert "cannot transition from `done`" in capsys.readouterr().err


def test_status_fallback_uses_task_state_and_status_at(tmp_path: Path) -> None:
    plan = tmp_path / "plans" / "sample" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\ntype: plan\nid: sample\nstatus: active\n---\n")
    _task(
        plan.parent / "tasks" / "one.md",
        "in_review",
    ).write_text(
        "---\ntype: task\ntitle: Review API\nstatus: in_review\n"
        f"status_at: '{datetime.now(UTC).isoformat()}'\n---\n",
        encoding="utf-8",
    )

    report = status.read_plan(plan, stall_minutes=60)

    assert report is not None
    assert report["task_now"] == "Review API in review"

    task = plan.parent / "tasks" / "one.md"
    task.write_text(
        "---\ntype: task\ntitle: Review API\nstatus: in_review\n"
        f"status_at: '{(datetime.now(UTC) - timedelta(hours=3)).isoformat()}'\n---\n",
        encoding="utf-8",
    )
    stalled = status.read_plan(plan, stall_minutes=60)
    assert stalled is not None
    assert stalled["task_now"].startswith("Review API stalled ")
