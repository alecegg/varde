# ruff: noqa: S603, S607
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_workflow.commands.plan_gate import run
from varde_workflow.execution_wave import dependency_chain


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(root: Path, message: str = "change") -> str:
    _git(root, "add", ".")
    _git(
        root, "-c", "user.name=T", "-c", "user.email=t@e.com", "commit", "-qm", message
    )
    return _git(root, "rev-parse", "HEAD")


def _task(tasks: Path, name: str, depends: list[str], owns: list[str] | None) -> Path:
    owns_line = f"owns: {owns!r}\n" if owns is not None else ""
    path = tasks / f"{name}.md"
    path.write_text(
        f"---\ntype: task\nstatus: todo\ndepends_on: {depends!r}\n{owns_line}---\n\n"
        "## Acceptance criteria\n- done\n",
        encoding="utf-8",
    )
    return path


def _plan(
    tmp_path: Path,
    tasks: dict[str, tuple[list[str], list[str] | None]],
    scope: str = "",
    branch: bool = True,
) -> tuple[Path, dict[str, Path]]:
    root = tmp_path / "repo"
    (root / "plans" / "p" / "tasks").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    (root / "plans" / "p" / "plan.md").write_text(
        f"---\ntype: plan\nstatus: active\n{scope}---\n\n## Acceptance criteria\n- x\n",
        encoding="utf-8",
    )
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("a\n", encoding="utf-8")
    paths = {
        name: _task(root / "plans" / "p" / "tasks", name, deps, owns)
        for name, (deps, owns) in tasks.items()
    }
    _commit(root, "base")
    if branch:
        _git(root, "checkout", "-q", "-b", "work")
    return root, paths


def _gate(root: Path, task: Path, commit: str) -> tuple[int, str]:
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        status = run(SimpleNamespace(task=task, commit=commit, repo_root=root))
    return status, buffer.getvalue()


def _row(output: str, check: str) -> str:
    return next(
        (line for line in output.splitlines() if line.startswith(f"{check}, ")), ""
    )


@pytest.fixture(autouse=True)
def _no_scan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "varde"
    stub.write_text('#!/bin/sh\necho \'{"data":{"findings":[]}}\'\n', encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{__import__('os').environ['PATH']}")


def test_dependency_chain_detection() -> None:
    assert dependency_chain({"a": [], "b": ["a"], "c": ["b"]})
    assert dependency_chain({"a": []})
    assert not dependency_chain({"a": [], "b": []})
    assert not dependency_chain({"a": ["b"], "b": ["a"]})


def test_dependency_chain_cycle_and_dangling() -> None:
    assert not dependency_chain({"a": ["b"], "b": ["a"]})
    assert not dependency_chain({"a": ["a"]})
    assert dependency_chain({"a": ["missing"]})
    assert dependency_chain({"a": [], "b": ["a", "missing"]})
    assert not dependency_chain({"a": ["missing"], "b": []})


def test_chain_touch_and_revert_passes(tmp_path: Path) -> None:
    root, tasks = _plan(
        tmp_path,
        {"one": ([], None), "two": (["one"], None)},
        scope='scope: ["src/**"]\n',
    )
    (root / "other.txt").write_text("x\n", encoding="utf-8")
    _commit(root, "touch")
    _git(root, "rm", "-q", "other.txt")
    (root / "src" / "a.py").write_text("b\n", encoding="utf-8")
    commit = _commit(root, "revert")

    status, output = _gate(root, tasks["two"], commit)

    assert _row(output, "scope").startswith("scope, pass,")
    assert "ownership," not in output
    assert status == 0


def test_scope_violation_message(tmp_path: Path) -> None:
    root, tasks = _plan(
        tmp_path,
        {"one": ([], None)},
        scope='scope: ["workflow/src/varde_workflow/**"]\n',
    )
    (root / "docs").mkdir()
    (root / "docs" / "x.md").write_text("x\n", encoding="utf-8")
    commit = _commit(root)

    status, output = _gate(root, tasks["one"], commit)

    assert status != 0
    assert "GATE-001 high: scope: docs/x.md" in output
    assert "Fix: add the path to `scope:` in plan.md" in output


def test_independent_tasks_keep_ownership(tmp_path: Path) -> None:
    root, tasks = _plan(
        tmp_path,
        {"one": ([], ["src/a.py"]), "two": ([], ["src/b.py"])},
    )
    (root / "src" / "a.py").write_text("n\n", encoding="utf-8")
    commit = _commit(root)

    _, output = _gate(root, tasks["one"], commit)

    assert _row(output, "ownership").startswith("ownership, pass,")
    assert "scope," not in output


def test_serial_plan_gets_parallel_later(tmp_path: Path) -> None:
    root, tasks = _plan(tmp_path, {"one": ([], ["src/a.py"])})
    (root / "src" / "a.py").write_text("n\n", encoding="utf-8")
    commit = _commit(root)
    _, output = _gate(root, tasks["one"], commit)
    assert _row(output, "scope").startswith("scope, pass,")

    _task(root / "plans" / "p" / "tasks", "extra", [], ["src/c.py"])
    commit = _commit(root, "extra")
    _, output = _gate(root, tasks["one"], commit)
    assert "ownership," in output
    assert "scope," not in output


def test_missing_scope_derives_from_tasks(tmp_path: Path) -> None:
    root, tasks = _plan(tmp_path, {"one": ([], ["src/a.py"])})
    (root / "src" / "a.py").write_text("n\n", encoding="utf-8")
    (root / "stray.py").write_text("s\n", encoding="utf-8")
    commit = _commit(root)

    status, output = _gate(root, tasks["one"], commit)

    assert status != 0
    assert _row(output, "scope").startswith("scope, fail, stray.py")


def test_missing_scope_without_declarations_skipped(tmp_path: Path) -> None:
    root, tasks = _plan(tmp_path, {"one": ([], None)})
    (root / "any.py").write_text("s\n", encoding="utf-8")
    commit = _commit(root)

    _, output = _gate(root, tasks["one"], commit)

    assert _row(output, "scope").startswith("scope, skipped,")


def test_commit_on_default_branch_has_empty_net_diff(tmp_path: Path) -> None:
    root, tasks = _plan(
        tmp_path, {"one": ([], None)}, scope='scope: ["nothing/**"]\n', branch=False
    )
    (root / "docs.md").write_text("x\n", encoding="utf-8")
    commit = _commit(root)

    status, output = _gate(root, tasks["one"], commit)

    assert _row(output, "scope").startswith("scope, pass,")
    assert status == 0


def test_no_default_branch_fails_clearly(tmp_path: Path) -> None:
    root, tasks = _plan(tmp_path, {"one": ([], None)}, scope='scope: ["src/**"]\n')
    _git(root, "branch", "-m", "work", "feature")
    _git(root, "branch", "-D", "main")
    commit = _git(root, "rev-parse", "HEAD")

    status, output = _gate(root, tasks["one"], commit)

    assert status != 0
    assert "no default branch found" in _row(output, "scope")


def test_plan_memory_dir_is_exempt(tmp_path: Path) -> None:
    root, tasks = _plan(tmp_path, {"one": ([], None)}, scope='scope: ["src/**"]\n')
    (root / "plans" / "p" / "tasks" / "one.md").write_text("---\nstatus: done\n---\n")
    commit = _commit(root)

    _, output = _gate(root, tasks["one"], commit)

    assert _row(output, "scope").startswith("scope, pass,")


def test_bare_directory_scope_entry_need_not_exist(tmp_path: Path) -> None:
    root, tasks = _plan(
        tmp_path, {"one": ([], None)}, scope='scope: ["newdir", "exact.py"]\n'
    )
    (root / "newdir").mkdir()
    (root / "newdir" / "x.py").write_text("x\n", encoding="utf-8")
    (root / "exact.py").write_text("x\n", encoding="utf-8")
    commit = _commit(root)

    _, output = _gate(root, tasks["one"], commit)

    assert _row(output, "scope").startswith("scope, pass,")


def test_derived_scope_ignores_rename_paths(tmp_path: Path) -> None:
    root, tasks = _plan(tmp_path, {"one": ([], ["src/a.py"])})
    tasks["one"].write_text(
        "---\ntype: task\nstatus: todo\ndepends_on: []\nowns: ['src/a.py']\n"
        "renames: ['old.py -> new.py']\n---\n\n## Acceptance criteria\n- done\n",
        encoding="utf-8",
    )
    (root / "old.py").write_text("o\n", encoding="utf-8")
    (root / "new.py").write_text("o\n", encoding="utf-8")
    commit = _commit(root)

    _, output = _gate(root, tasks["one"], commit)

    assert _row(output, "scope").startswith("scope, fail,")
    assert "old.py" in _row(output, "scope")
    assert "new.py" in _row(output, "scope")


def test_plan_memory_exemption_on_symlinked_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    root, _tasks = _plan(real, {"one": ([], None)}, scope='scope: ["src/**"]\n')
    (root / "plans" / "p" / "tasks" / "one.md").write_text("---\nstatus: done\n---\n")
    commit = _commit(root)
    linked_root = link / "repo"

    _, output = _gate(linked_root, linked_root / "plans/p/tasks/one.md", commit)

    assert _row(output, "scope").startswith("scope, pass,")
