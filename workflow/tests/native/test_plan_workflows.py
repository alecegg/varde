from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_workflow.commands import status
from varde_workflow.commands.distill import distill
from varde_workflow.commands.graph import graph_data
from varde_workflow.commands.readiness import readiness_data
from varde_workflow.commands.validate import run as validate_run
from varde_workflow.conclusion import ConcludeError, conclude
from varde_workflow.execution_wave import execution_wave
from varde_workflow.task_ownership import check


def write_plan(path: Path, *, state: str = "active", body: str = "") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    plan = path / "plan.md"
    plan.write_text(
        f"---\ntype: plan\nid: {path.name}\nstatus: {state}\n---\n{body}",
        encoding="utf-8",
    )
    return plan


def write_task(
    path: Path, task_id: str, *, state: str = "todo", depends: str = "", owns: str = ""
) -> Path:
    tasks = path / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    dependency = f"depends_on: [{depends}]\n" if depends else ""
    ownership = f"owns: [{owns}]\n" if owns else ""
    task = tasks / f"{task_id}.md"
    task.write_text(
        f"---\ntype: task\nid: {task_id}\nstatus: {state}\n"
        f"{dependency}{ownership}---\n",
        encoding="utf-8",
    )
    return task


def test_validate_reports_missing_section_and_graph_reports_unknown_task_dependency(
    tmp_path: Path, capsys
) -> None:
    plan = write_plan(tmp_path / "plans" / "sample", body="## Problem\nA small plan.\n")
    assert validate_run(SimpleNamespace(artifact=str(plan), json=False)) == 4
    assert "Acceptance criteria" in capsys.readouterr().err

    task = write_task(plan.parent, "first", depends="missing")
    graph, _ = graph_data(str(task))
    assert graph["blockers"] == [
        {
            "code": "dependency_missing",
            "artifact_id": "first",
            "dependency": "missing",
            "status": None,
        }
    ]


def test_validate_accepts_a_complete_plan(tmp_path: Path, capsys) -> None:
    plan = write_plan(
        tmp_path / "plans" / "complete",
        body="## Problem\nA small plan.\n\n## Acceptance criteria\n- It validates.\n",
    )
    assert validate_run(SimpleNamespace(artifact=str(plan), json=False)) == 0
    assert capsys.readouterr().err == ""


def test_graph_and_readiness_report_edges_and_available_tasks(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    root = tasks / "b.md"
    root.write_text("---\ntype: task\nid: b\nstatus: todo\ndepends_on: [a]\n---\n")
    (tasks / "a.md").write_text("---\ntype: task\nid: a\nstatus: todo\n---\n")

    graph, _ = graph_data(str(root))
    readiness = readiness_data(str(root))

    assert [(edge["from"], edge["to"]) for edge in graph["edges"]] == [("b", "a")]
    assert readiness["ready"] is False
    (tasks / "a.md").write_text(
        "---\ntype: task\nid: a\nstatus: done\n---\n", encoding="utf-8"
    )
    assert readiness_data(str(root))["ready"] is True


def _committed_repo(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.invalid"],
        check=True,
    )


class NoDependents:
    def dependents(self, repo_root: Path, path: Path) -> list[Path]:
        return []


@pytest.mark.parametrize(
    ("ownership", "expected"),
    [
        (("src/a.py", "src/b.py"), ["a", "b"]),
        (("src/shared.py", "src/shared.py"), ["a"]),
    ],
)
def test_execution_wave_groups_only_non_conflicting_tasks(
    tmp_path: Path, ownership: tuple[str, str], expected: list[str]
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    plan = root / "plan"
    _committed_repo(root)
    write_task(plan, "a", owns=ownership[0])
    write_task(plan, "b", owns=ownership[1])

    result = execution_wave(plan, root, 2, NoDependents())

    assert result["next_wave"] == expected


def test_ownership_check_names_commit_path_outside_task_declaration(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _committed_repo(root)
    task = write_task(root / "plan", "sample", owns="src/owned.py")
    (root / "src").mkdir()
    (root / "src" / "owned.py").write_text("owned\n", encoding="utf-8")
    (root / "stray.py").write_text("stray\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "initial"], check=True)
    (root / "stray.py").write_text("changed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "stray.py"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "change"], check=True)

    audit = check(task, "HEAD", root, [])

    assert audit.status == "stray"
    assert audit.stray == ["stray.py"]


def test_status_excludes_concluded_plans(tmp_path: Path) -> None:
    working = tmp_path / "working"
    write_plan(working / "plans" / "active", body="## Acceptance criteria\n- active\n")
    write_plan(working / "plans" / "finished", state="completed")

    report = status.collect_from(working)

    assert [item["id"] for item in report["plans"]] == ["active"]


def test_conclude_requires_review_and_completes_reviewed_plan(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _committed_repo(root)
    subprocess.run(
        ["git", "-C", str(root), "commit", "--allow-empty", "-qm", "review"], check=True
    )
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    plan_dir = tmp_path / "plans" / "sample"
    plan = write_plan(plan_dir, body="## Acceptance criteria\n- done\n")
    with pytest.raises(ConcludeError, match="review.md"):
        conclude(plan_dir, "HEAD", root)

    (plan_dir / "review.md").write_text(
        f"---\nverdict: approved\nhead: {head}\n---\n", encoding="utf-8"
    )
    conclude(plan_dir, "HEAD", root)

    assert "status: completed" in plan.read_text(encoding="utf-8")


def test_distill_prints_skeleton_headings_without_changing_plan_tree(
    tmp_path: Path,
) -> None:
    plan_dir = tmp_path / "plans" / "sample"
    write_plan(
        plan_dir,
        state="completed",
        body=(
            "# Sample\n\n## Problem\nNeed.\n\n## Solution\nDo.\n"
            "\n## Decisions so far\nKeep.\n"
        ),
    )
    write_task(plan_dir, "done", state="done")
    before = {
        path.relative_to(plan_dir): hashlib.sha256(path.read_bytes()).digest()
        for path in plan_dir.rglob("*")
        if path.is_file()
    }

    draft = distill(plan_dir, tmp_path)

    assert all(
        f"## {heading}" in draft.markdown
        for heading in (
            "Problem",
            "Solution",
            "Decisions so far",
            "Tasks",
            "Review",
            "Why",
            "Lessons",
            "Measurements",
        )
    )
    assert {
        path.relative_to(plan_dir): hashlib.sha256(path.read_bytes()).digest()
        for path in plan_dir.rglob("*")
        if path.is_file()
    } == before


def test_watch_emits_stale_event_for_old_plan_without_waiting(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from varde_workflow.commands.watch import run_watch

    working = tmp_path / "working"
    plan = write_plan(working / "plans" / "stale")
    old = time.time() - 3
    plan.touch()
    import os

    os.utime(plan, (old, old))
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))

    args = SimpleNamespace(
        once=True,
        no_inbox=True,
        no_wake=True,
        stale=1,
        interval=60,
        repo=tmp_path,
        json=False,
    )
    assert run_watch(args) == 0
    assert capsys.readouterr().out.startswith("idle-no-handback stale ")
