from __future__ import annotations

from pathlib import Path

from varde_workflow.plan_overlap import plan_overlaps


def _plan(root: Path, name: str, *, status: str = "active", shared: str = "[]") -> Path:
    directory = root / name
    (directory / "tasks").mkdir(parents=True)
    (directory / "plan.md").write_text(
        f"---\ntype: plan\nstatus: {status}\nshared: {shared}\n---\n"
    )
    return directory


def _task(plan: Path, name: str, owns: str, *, status: str = "todo") -> None:
    (plan / "tasks" / f"{name}.md").write_text(
        f"---\nstatus: {status}\nowns: [{owns}]\n---\n"
    )


def test_plan_overlaps_reports_sorted_overlapping_files(tmp_path: Path) -> None:
    current = _plan(tmp_path, "current")
    _task(current, "one", "src/*.py")
    sibling = _plan(tmp_path, "z-sibling")
    _task(sibling, "one", "src/a.py")
    other = _plan(tmp_path, "a-sibling")
    _task(other, "one", "src/b.py")

    assert plan_overlaps(current, [sibling, other]) == [
        {"plan": "a-sibling", "files": ["src/b.py"]},
        {"plan": "z-sibling", "files": ["src/a.py"]},
    ]


def test_plan_overlaps_returns_empty_for_disjoint_declarations(tmp_path: Path) -> None:
    current = _plan(tmp_path, "current")
    _task(current, "one", "src/a*.py")
    sibling = _plan(tmp_path, "sibling")
    _task(sibling, "one", "src/b*.py")

    assert plan_overlaps(current, [sibling]) == []


def test_plan_overlaps_skips_done_tasks_and_terminal_plans(tmp_path: Path) -> None:
    current = _plan(tmp_path, "current")
    _task(current, "one", "src/**")
    terminal = _plan(tmp_path, "terminal", status="completed")
    _task(terminal, "one", "src/a.py")
    sibling = _plan(tmp_path, "sibling")
    _task(sibling, "done", "src/a.py", status="done")

    assert plan_overlaps(current, [terminal, sibling]) == []


def test_plan_overlaps_skips_cancelled_sibling(tmp_path: Path) -> None:
    current = _plan(tmp_path, "current")
    _task(current, "one", "src/**")
    cancelled = _plan(tmp_path, "cancelled", status="cancelled")
    _task(cancelled, "one", "src/a.py")

    assert plan_overlaps(current, [cancelled]) == []


def test_plan_overlaps_skips_self(tmp_path: Path) -> None:
    current = _plan(tmp_path, "current")
    _task(current, "one", "src/**")

    assert plan_overlaps(current, [current]) == []


def test_plan_overlaps_includes_shared_and_generated_paths(tmp_path: Path) -> None:
    current = _plan(tmp_path, "current", shared="[./uv.lock]")
    sibling = _plan(tmp_path, "sibling", shared="[uv.lock]")
    _task(sibling, "one", "other.py")

    assert plan_overlaps(current, [sibling]) == [
        {"plan": "sibling", "files": ["uv.lock"]}
    ]


def test_plan_without_tasks_has_no_overlaps(tmp_path: Path) -> None:
    current = _plan(tmp_path, "current")
    (current / "tasks").rmdir()
    sibling = _plan(tmp_path, "sibling")
    _task(sibling, "one", "src/**")

    assert plan_overlaps(current, [sibling]) == []


def test_plan_overlaps_skips_malformed_sibling(tmp_path: Path) -> None:
    current = _plan(tmp_path, "current")
    _task(current, "one", "src/**")
    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / "plan.md").write_text("not frontmatter")

    assert plan_overlaps(current, [malformed]) == []


def test_plan_overlaps_skips_sibling_with_invalid_owns(tmp_path: Path) -> None:
    current = _plan(tmp_path, "current")
    _task(current, "one", "src/**")
    sibling = _plan(tmp_path, "sibling")
    (sibling / "tasks" / "bad.md").write_text("---\nowns: nope\n---\n")

    assert plan_overlaps(current, [sibling]) == []


def test_plan_overlaps_normalizes_paths_and_sorts_files(tmp_path: Path) -> None:
    current = _plan(tmp_path, "current")
    _task(current, "one", "./src/**")
    sibling = _plan(tmp_path, "sibling")
    _task(sibling, "one", "src/z.py")
    _task(sibling, "two", "src/a.py")

    assert plan_overlaps(current, [sibling]) == [
        {"plan": "sibling", "files": ["src/a.py", "src/z.py"]}
    ]
