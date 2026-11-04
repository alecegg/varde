from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

from varde_workflow import merge_approval
from varde_workflow.commands import (
    approve_merge,
    assign,
    conclude,
    owner,
    plan_answer,
    task_set,
)
from varde_workflow.merge_approval import Approval

sys.path.insert(0, str(Path(__file__).parent))
from golden.plans.builder import build, check_snapshot


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls.fromtimestamp(1_700_000_100, UTC)
        return value if tz is None else value.astimezone(tz)


class LaterDateTime(FixedDateTime):
    @classmethod
    def now(cls, tz=None):
        value = cls.fromtimestamp(1_700_000_200, UTC)
        return value if tz is None else value.astimezone(tz)


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2023, 11, 14)


def _snapshot(name: str, output: str, path: Path, root: Path) -> None:
    check_snapshot(
        name,
        json.dumps(
            {
                "output": output.replace(str(root), "<TMP>"),
                "bytes": path.read_bytes().decode("utf-8"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        root,
    )


def _run_snapshot(name: str, run, path: Path, root: Path) -> None:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert run() == 0
    _snapshot(name, output.getvalue(), path, root)


def _run_error_snapshot(name: str, run, path: Path, root: Path) -> None:
    output = io.StringIO()
    errors = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        code = run()
    _snapshot(name, f"exit={code}\n{output.getvalue()}{errors.getvalue()}", path, root)


def _setup(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    working, repo = build(tmp_path)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.chdir(working)
    monkeypatch.setattr(task_set.dt, "datetime", FixedDateTime)
    monkeypatch.setattr(plan_answer, "date", FixedDate)
    return working, repo


def test_task_set_writer_goldens(tmp_path: Path, monkeypatch) -> None:
    working, _ = _setup(tmp_path, monkeypatch)
    cases = (
        ("todo-active", "task.md", "in_progress"),
        ("active-fixing", "active.md", "fixing"),
        ("fixing-blocked", "task.md", "blocked"),
        ("active-done", "task.md", "done"),
        ("done-rejected", "task.md", "fixing"),
    )
    for name, relative, state in cases:
        task = working / "plans/group/nested/tasks" / relative
        if name == "active-fixing":
            task.write_text(
                "---\ntype: task\nid: active\ntitle: Active task\n"
                "status: in_progress\n---\n",
                encoding="utf-8",
            )
        elif name == "fixing-blocked":
            task.write_text(
                "---\ntype: task\nid: task\ntitle: Task\nstatus: fixing\n---\n",
                encoding="utf-8",
            )
        elif name == "active-done":
            task.write_text(
                "---\ntype: task\nid: task\ntitle: Task\nstatus: in_progress\n---\n",
                encoding="utf-8",
            )
        elif name == "done-rejected":
            task.write_text(
                "---\ntype: task\nid: task\ntitle: Task\nstatus: done\n---\n",
                encoding="utf-8",
            )
        args = SimpleNamespace(task=task, state=state, json=True)
        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = task_set.run(args)
        if name == "done-rejected":
            assert code == 1
            _snapshot(name, output.getvalue() + errors.getvalue(), task, tmp_path)
        else:
            assert code == 0
            _snapshot(name, output.getvalue() + errors.getvalue(), task, tmp_path)


def test_owner_writer_goldens(tmp_path: Path, monkeypatch) -> None:
    working, _ = _setup(tmp_path, monkeypatch)
    plan = working / "plans/group/nested/plan.md"
    original = plan.read_bytes()
    for name, contents, value in (
        ("owner-absent", original, "codex:agent-1"),
        (
            "owner-present",
            original.replace(
                b"title: Nested\n", b"title: Nested\nowner: 'old:owner'\n"
            ),
            "codex:agent-1",
        ),
        (
            "owner-continuation",
            original.replace(
                b"title: Nested\n",
                b"title: Nested\nowner: |\n  old:owner\n  detail: legacy\n",
            ),
            "codex:agent-1",
        ),
        (
            "owner-clear",
            original.replace(
                b"title: Nested\n", b"title: Nested\nowner: 'old:owner'\n"
            ),
            None,
        ),
        ("owner-crlf", original.replace(b"\n", b"\r\n"), "codex:agent-1"),
        ("owner-no-final-newline", original.rstrip(b"\n"), "codex:agent-1"),
    ):
        plan.write_bytes(contents)
        args = SimpleNamespace(plan=plan, owner=value, clear=value is None, json=False)
        if name == "owner-crlf":
            # Current behavior rejects CRLF frontmatter; this golden records that.
            _run_error_snapshot(name, lambda args=args: owner.run(args), plan, tmp_path)
        else:
            _run_snapshot(name, lambda args=args: owner.run(args), plan, tmp_path)


def test_assign_writer_goldens(tmp_path: Path, monkeypatch) -> None:
    working, _ = _setup(tmp_path, monkeypatch)
    plan = working / "plans/group/nested/plan.md"
    for name, slot, clear in (
        ("assign-set", "orchestrator-1", False),
        ("assign-clear", None, True),
    ):
        args = SimpleNamespace(plan=plan, slot=slot, clear=clear, json=False)
        _run_snapshot(name, lambda args=args: assign.run(args), plan, tmp_path)


def test_approve_merge_first_write_wins_golden(tmp_path: Path, monkeypatch) -> None:
    working, _ = _setup(tmp_path, monkeypatch)
    plan = working / "plans/group/nested/plan.md"
    for index, name in enumerate(("approve-merge-first", "approve-merge-repeat")):
        stamp = FixedDateTime.now(UTC) if index == 0 else LaterDateTime.now(UTC)
        approval = Approval("plan", stamp.isoformat(timespec="seconds"))
        monkeypatch.setattr(
            merge_approval, "fetch_approval", lambda _id, _reviewed, a=approval: a
        )
        _run_snapshot(
            name,
            lambda: approve_merge.run(SimpleNamespace(plan=plan, json=False)),
            plan,
            tmp_path,
        )


def test_plan_answer_writer_golden(tmp_path: Path, monkeypatch) -> None:
    working, _ = _setup(tmp_path, monkeypatch)
    plan = working / "plans/group/nested/plan.md"
    plan.write_bytes(plan.read_bytes() + b"\n## Open Questions\n- Which option?\n")
    args = SimpleNamespace(
        plan=plan, question="Which option?", answer="Keep it", json=True
    )
    _run_snapshot("plan-answer", lambda: plan_answer.run(args), plan, tmp_path)


def test_conclude_writer_golden(tmp_path: Path, monkeypatch) -> None:
    working, repo = _setup(tmp_path, monkeypatch)
    plan_dir = working / "plans/group/nested"
    plan = plan_dir / "plan.md"
    head = subprocess.check_output(  # noqa: S603 - Uses a controlled fixture repository.
        ["git", "-C", str(repo), "rev-parse", "HEAD"],  # noqa: S607
        text=True,
    ).strip()
    (plan_dir / "review.md").write_text(
        f"---\nverdict: approved\nhead: {head}\n---\n", encoding="utf-8"
    )
    args = SimpleNamespace(plan=plan_dir, merged="HEAD", repo=repo, json=True)
    _run_snapshot("conclude", lambda: conclude.run(args), plan, tmp_path)
