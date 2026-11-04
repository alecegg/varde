from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from varde_workflow.commands.readiness import readiness_data, run


def _artifact(path: Path, frontmatter: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n", encoding="utf-8")
    return path


def _plan(root: Path, name: str, owns: str) -> Path:
    directory = root / name
    _artifact(directory / "plan.md", "type: plan\nstatus: active")
    _artifact(directory / "tasks" / "one.md", f"status: todo\nowns: [{owns}]")
    return directory


def test_readiness_reports_sibling_overlap_and_text_warning(
    tmp_path: Path, capsys
) -> None:
    plans = tmp_path / "plans"
    current = _plan(plans, "current", "src/*.py")
    _plan(plans, "sibling", "src/app.py")

    data = readiness_data(str(current / "plan.md"))
    code = run(SimpleNamespace(plan=str(current / "plan.md"), json=False))

    output = capsys.readouterr().out
    assert code == 0
    assert data["overlap_warnings"] == [{"plan": "sibling", "files": ["src/app.py"]}]
    assert "warning: overlaps sibling on src/app.py" in output
    assert data["ready"] is True
    assert data["planning_ready"] is True
    assert data["implementation_ready"] is True


def test_readiness_non_plan_input_has_no_overlap_warning(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    current = _plan(plans, "current", "src/**")
    _plan(plans, "sibling", "src/app.py")
    task = _artifact(current / "tasks" / "one.md", "type: task\nstatus: todo")

    assert readiness_data(str(task))["overlap_warnings"] == []


def test_readiness_overlap_does_not_change_exit_code_or_ready(
    tmp_path: Path, capsys
) -> None:
    current = _plan(tmp_path / "plans", "current", "src/**")
    baseline = readiness_data(str(current / "plan.md"))
    _plan(tmp_path / "plans", "sibling", "src/app.py")

    code = run(SimpleNamespace(plan=str(current / "plan.md"), json=True))
    payload = json.loads(capsys.readouterr().out)["data"]

    assert code == 0
    assert payload["ready"] == baseline["ready"]
    assert payload["planning_ready"] == baseline["planning_ready"]
    assert payload["implementation_ready"] == baseline["implementation_ready"]


def test_readiness_skips_malformed_sibling(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    current = _plan(plans, "current", "src/**")
    malformed = plans / "malformed"
    malformed.mkdir()
    (malformed / "plan.md").write_text("not frontmatter", encoding="utf-8")

    assert readiness_data(str(current / "plan.md"))["overlap_warnings"] == []


def test_readiness_bad_current_owns_returns_no_overlap_warnings(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    current = _plan(plans, "current", "src/**")
    _plan(plans, "sibling", "src/app.py")
    (current / "tasks" / "one.md").write_text(
        "---\nstatus: todo\nowns: nope\n---\n", encoding="utf-8"
    )

    assert readiness_data(str(current / "plan.md"))["overlap_warnings"] == []


def test_readiness_ignores_nested_plans_and_keeps_backlog_sibling(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "plans"
    current = _plan(plans, "current", "src/**")
    backlog = _plan(plans, "backlog", "src/app.py")
    (backlog / "plan.md").write_text(
        "---\ntype: plan\nstatus: backlog\n---\n", encoding="utf-8"
    )
    for parent in ("notes", "tasks"):
        nested = plans / "container" / parent / "nested"
        _artifact(nested / "plan.md", "type: plan\nstatus: active")
        _artifact(nested / "tasks" / "one.md", "status: todo\nowns: [src/app.py]")

    assert readiness_data(str(current / "plan.md"))["overlap_warnings"] == [
        {"plan": "backlog", "files": ["src/app.py"]}
    ]


def test_readiness_text_limits_displayed_files_and_reports_remaining_count(
    tmp_path: Path, capsys
) -> None:
    plans = tmp_path / "plans"
    current = _plan(plans, "current", "src/**")
    sibling = plans / "sibling"
    _artifact(sibling / "plan.md", "type: plan\nstatus: active")
    for index in range(7):
        _artifact(
            sibling / "tasks" / f"{index}.md",
            f"status: todo\nowns: [src/file-{index}.py]",
        )

    assert run(SimpleNamespace(plan=str(current / "plan.md"), json=False)) == 0
    output = capsys.readouterr().out
    assert (
        "warning: overlaps sibling on src/file-0.py, src/file-1.py, src/file-2.py, src/file-3.py, src/file-4.py, and 2 more"
        in output
    )
