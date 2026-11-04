from pathlib import Path

from varde_workflow.commands.plan_detail import plan_detail, task_detail


def make(tmp_path: Path) -> Path:
    plan = tmp_path / "plans" / "p1"
    (plan / "tasks").mkdir(parents=True)
    (plan / "plan.md").write_text(
        "---\ntype: plan\ntitle: P\nstatus: backlog\n---\nbody\n"
    )
    (plan / "tasks" / "t1.md").write_text(
        "---\ntype: task\nstatus: todo\nowns: [a]\n---\ndo it\n"
    )
    return tmp_path


def test_plan_and_task_detail(tmp_path: Path) -> None:
    working = make(tmp_path)
    detail = plan_detail(working, "p1")
    assert detail is not None
    assert detail["tasks"][0]["id"] == "t1"
    task = task_detail(working, "p1", "t1")
    assert task is not None
    assert task["fields"]["status"] == "todo"
    assert "do it" in task["body"]


def test_unknown_and_traversal_are_none(tmp_path: Path) -> None:
    working = make(tmp_path)
    assert plan_detail(working, "nope") is None
    assert task_detail(working, "p1", "missing") is None
    assert task_detail(working, "p1", "../plan") is None
