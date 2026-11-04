"""`varde plan merge` and the recordless-merge flag in `varde plan merged`."""

from __future__ import annotations

import subprocess
from argparse import Namespace
from pathlib import Path

import pytest
from varde_workflow import merge_approval
from varde_workflow.commands import merge, merged
from varde_workflow.inbox import read_all
from varde_workflow.merge_approval import Approval, ApprovalUnavailable


def git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed git operations in a temp repo
        ["git", "-C", str(repo), *args],  # noqa: S607 - fixed system git executable
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A main checkout with a plan `demo` on branch worktree/demo (one commit ahead)."""
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.test")
    git(tmp_path, "config", "user.name", "T")
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path / "working"))
    plan = tmp_path / "working" / "plans" / "demo" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\ntype: plan\nid: demo\nstatus: active\n---\n")
    (tmp_path / "README").write_text("r\n")
    git(tmp_path, "add", "README")
    git(tmp_path, "commit", "-qm", "init")
    git(tmp_path, "switch", "-qc", "worktree/demo")
    (tmp_path / "work.txt").write_text("w\n")
    git(tmp_path, "add", "work.txt")
    git(tmp_path, "commit", "-qm", "work")
    git(tmp_path, "switch", "-q", "main")
    (tmp_path / "main.txt").write_text("m\n")
    git(tmp_path, "add", "main.txt")
    git(tmp_path, "commit", "-qm", "main moves")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def args() -> Namespace:
    return Namespace(plan="demo/plan.md", json=False)


def approved(monkeypatch) -> None:
    value = Approval("demo", "2026-01-02")
    monkeypatch.setattr(merge_approval, "fetch_approval", lambda _id, _reviewed: value)


def test_merge_refuses_without_a_record_and_changes_nothing(
    repo, monkeypatch, capsys
) -> None:
    head = git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(merge_approval, "fetch_approval", lambda _id, _reviewed: None)
    assert merge.run(args()) == 1
    assert "no merge approval is recorded for demo" in capsys.readouterr().err
    assert git(repo, "rev-parse", "HEAD") == head


def test_merge_refuses_when_the_runner_is_unreachable(
    repo, monkeypatch, capsys
) -> None:
    def down(_id, _reviewed):
        raise ApprovalUnavailable("merge approval record unavailable: refused")

    monkeypatch.setattr(merge_approval, "fetch_approval", down)
    assert merge.run(args()) == 1
    assert "unavailable" in capsys.readouterr().err


def test_merge_refuses_off_main(repo, monkeypatch, capsys) -> None:
    approved(monkeypatch)
    git(repo, "switch", "-qc", "side")
    assert merge.run(args()) == 1
    assert "main checkout" in capsys.readouterr().err


def test_merge_with_a_record_merges_the_plan_branch(repo, monkeypatch) -> None:
    approved(monkeypatch)
    assert merge.run(args()) == 0
    assert (repo / "work.txt").exists()
    assert git(repo, "merge-base", "--is-ancestor", "worktree/demo", "main") == ""
    plan = repo / "working" / "plans" / "demo" / "plan.md"
    assert "merge_approved_at: 2026-01-02" in plan.read_text()


def test_merged_flags_a_merge_with_no_record_and_posts_one_mailbox_item(
    repo, monkeypatch, capsys
) -> None:
    git(repo, "merge", "--no-ff", "--no-edit", "-q", "worktree/demo")
    monkeypatch.setattr(merged, "fetch_approval", lambda _id, _reviewed: None)
    assert merged.run(args()) == merged.UNAPPROVED_EXIT
    assert merged.run(args()) == merged.UNAPPROVED_EXIT
    assert "no user merge approval is recorded" in capsys.readouterr().err
    working = repo / "working"
    items = [m for m in read_all(working) if "without a recorded approval" in m.text]
    assert len(items) == 1
    assert (items[0].from_, items[0].to, items[0].kind) == (
        "merge-gate",
        "main",
        "needs-user",
    )


def test_merged_is_quiet_when_the_record_exists_or_is_unchecked(
    repo, monkeypatch, capsys
) -> None:
    git(repo, "merge", "--no-ff", "--no-edit", "-q", "worktree/demo")
    monkeypatch.setattr(
        merged, "fetch_approval", lambda _id, _reviewed: Approval("demo", "2026-01-02")
    )
    assert merged.run(args()) == 0

    def down(_id, _reviewed):
        raise ApprovalUnavailable("merge approval record unavailable: refused")

    monkeypatch.setattr(merged, "fetch_approval", down)
    assert merged.run(args()) == 0
    assert "approval not checked" in capsys.readouterr().err


def test_merged_is_one_before_the_branch_lands(repo, monkeypatch) -> None:
    monkeypatch.setattr(merged, "fetch_approval", lambda _id, _reviewed: None)
    assert merged.run(args()) == 1
