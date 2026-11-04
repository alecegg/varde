from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_workflow.commands.plan_gate import run


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(
    tmp_path: Path,
    *,
    gate: object | None = None,
    owns_extra: list[str] | None = None,
) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    root.mkdir()
    _git_init(root)
    plan = root / "plans" / "sample"
    tasks = plan / "tasks"
    tasks.mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "owned.py").write_text("old\n", encoding="utf-8")
    gate_line = f"gate: {json.dumps(gate)}\n" if gate is not None else ""
    (plan / "plan.md").write_text(
        f"---\ntype: plan\nstatus: active\n{gate_line}---\n\n"
        "## Acceptance criteria\n- done\n",
        encoding="utf-8",
    )
    task = tasks / "sample.md"
    owns = ["src/owned.py", *(owns_extra or [])]
    task.write_text(
        f"---\ntype: task\nstatus: todo\nowns: {owns!r}\n---\n\n"
        "## Acceptance criteria\n- done\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        "base",
    )
    _git(root, "checkout", "-q", "-b", "work")
    return root, task


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)


def _commit_change(root: Path, message: str = "change") -> str:
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        message,
    )
    return _git(root, "rev-parse", "HEAD")


def _stub_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: str) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "varde"
    stub.write_text(f"#!/bin/sh\necho '{response}'\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")


def test_gate_accepts_string_paths_at_command_boundary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, task = _repo(tmp_path)
    (root / "src" / "owned.py").write_text("new\n", encoding="utf-8")
    commit = _commit_change(root)
    _stub_scan(tmp_path, monkeypatch, '{"data":{"findings":[]}}')

    status = run(SimpleNamespace(task=str(task), commit=commit, repo_root=str(root)))

    assert status == 0
    assert "scope, pass," in capsys.readouterr().out


def test_gate_fails_stray_path_naming_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, task = _repo(tmp_path)
    (root / "src" / "owned.py").write_text("new\n", encoding="utf-8")
    (root / "stray.py").write_text("stray\n", encoding="utf-8")
    commit = _commit_change(root)

    status = run(SimpleNamespace(task=task, commit=commit, repo_root=root))

    output = capsys.readouterr().out
    assert status != 0
    assert "scope, fail," in output
    assert "stray.py" in output
    assert "GATE-" in output


def test_parallel_plan_gate_keeps_ownership_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, task = _repo(tmp_path)
    (task.parent / "other.md").write_text(
        "---\ntype: task\nstatus: todo\nowns: ['src/other.py']\n---\n\n"
        "## Acceptance criteria\n- done\n",
        encoding="utf-8",
    )
    (root / "src" / "owned.py").write_text("new\n", encoding="utf-8")
    (root / "stray.py").write_text("stray\n", encoding="utf-8")
    commit = _commit_change(root)

    status = run(SimpleNamespace(task=task, commit=commit, repo_root=root))

    output = capsys.readouterr().out
    assert status != 0
    assert "ownership, fail," in output
    assert "scope," not in output


def test_gate_names_failing_declared_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, task = _repo(tmp_path, gate=["false"])
    (root / "src" / "owned.py").write_text("new\n", encoding="utf-8")
    commit = _commit_change(root)

    status = run(SimpleNamespace(task=task, commit=commit, repo_root=root))

    assert status != 0
    output = capsys.readouterr().out
    assert "gate command 1 (false), fail," in output
    assert "false exited 1" in output


def test_missing_scan_index_fails_with_recovery_instruction(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, task = _repo(tmp_path)
    (root / "src" / "owned.py").write_text("new\n", encoding="utf-8")
    commit = _commit_change(root)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "varde"
    stub.write_text(
        '#!/bin/sh\necho \'{"ok":false,"data":{"error":{'
        '"code":"index_missing"}}}\'\nexit 1\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")

    status = run(SimpleNamespace(task=task, commit=commit, repo_root=root))

    output = capsys.readouterr().out
    assert status != 0
    assert "scan, fail," in output
    assert "GATE-001 high: scan:" in output
    assert "`varde map build` on the main checkout" in output
    assert "varde setup watch" not in output
    assert "scope, pass," in output


def test_gate_reports_size_over_budget(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, task = _repo(tmp_path)
    (root / "src" / "owned.py").write_text("new\n" + "x " * 150_000, encoding="utf-8")
    commit = _commit_change(root)
    status = run(SimpleNamespace(task=task, commit=commit, repo_root=root))

    assert status != 0
    assert "size, fail," in capsys.readouterr().out


def test_gate_runs_doc_lint_for_changed_skill(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, task = _repo(tmp_path, owns_extra=["workflow/skills/varde-demo/SKILL.md"])
    skill = root / "workflow" / "skills" / "varde-demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: varde-demo\ndescription: demo\n---\n", encoding="utf-8"
    )
    (root / "src" / "owned.py").write_text("new\n", encoding="utf-8")
    commit = _commit_change(root)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "varde"
    stub.write_text(
        '#!/bin/sh\nif [ "$1" = "scan" ]; then echo '
        '\'{"data":{"findings":[]}}\'; fi\nexit 0\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    status = run(SimpleNamespace(task=task, commit=commit, repo_root=root))

    assert status == 0
    assert "learn check, pass," in capsys.readouterr().out


def test_gate_rejects_non_ancestor_commit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, task = _repo(tmp_path)
    branch = _git(root, "branch", "--show-current")
    _git(root, "checkout", "--orphan", "unrelated")
    _git(root, "rm", "-rf", ".")
    (root / "other.py").write_text("other\n", encoding="utf-8")
    unrelated = _commit_change(root, "unrelated")
    _git(root, "checkout", branch)

    status = run(SimpleNamespace(task=task, commit=unrelated, repo_root=root))

    assert status != 0
    assert "not an ancestor of HEAD" in capsys.readouterr().out


def test_gate_accepts_older_ancestor_in_callers_worktree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, task = _repo(tmp_path)
    (root / "src" / "owned.py").write_text("first\n", encoding="utf-8")
    older = _commit_change(root, "task change")
    (root / "later.txt").write_text("later\n", encoding="utf-8")
    _commit_change(root, "later change")
    _stub_scan(tmp_path, monkeypatch, '{"data":{"findings":[]}}')

    status = run(SimpleNamespace(task=task, commit=older, repo_root=root))

    assert status == 0
    assert "scope, pass," in capsys.readouterr().out


def test_gate_rejects_non_list_gate_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, task = _repo(tmp_path, gate="false")
    (root / "src" / "owned.py").write_text("new\n", encoding="utf-8")
    commit = _commit_change(root)

    status = run(SimpleNamespace(task=task, commit=commit, repo_root=root))

    assert status != 0
    assert "gate commands, fail," in capsys.readouterr().out


def test_gate_fails_when_scope_has_no_tokens_header(tmp_path: Path) -> None:
    from varde_workflow.plan_gate import scope_tokens

    assert scope_tokens("review scope failed") is None


def test_gate_fails_changed_file_importing_higher_level_module(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, task = _repo(tmp_path, owns_extra=["low/src/lowpkg/mod.py"])
    (root / "layers.toml").write_text(
        '[module.low]\ndist = "low"\nlevel = 0\nwhy = "x"\n'
        '[module.high]\ndist = "high"\nlevel = 1\nwhy = "x"\n',
        encoding="utf-8",
    )
    for module, package in (("low", "lowpkg"), ("high", "highpkg")):
        pkg = root / module / "src" / package
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
    (root / "low" / "src" / "lowpkg" / "mod.py").write_text(
        "import highpkg\n", encoding="utf-8"
    )
    commit = _commit_change(root)
    _stub_scan(tmp_path, monkeypatch, '{"data":{"findings":[]}}')
    status = run(SimpleNamespace(task=task, commit=commit, repo_root=root))

    out = capsys.readouterr().out
    assert status != 0
    assert "layers, fail," in out
    assert "low/src/lowpkg/mod.py" in out
