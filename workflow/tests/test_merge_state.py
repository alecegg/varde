from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from varde_workflow.artifact import inspect
from varde_workflow.commands.approve_merge import approve_line
from varde_workflow.commands.watch import approved_merge_detail, frame_events
from varde_workflow.merge_state import awaiting_user, awaiting_user_message, is_merged


def _write_messages(working: Path, rows: list[dict[str, str]]) -> None:
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.records.messages import NewMessage

    messages = open_data(working, load_data_config()).messages
    for row in rows:
        messages.append(
            NewMessage(
                row.get("from", "orchestrator-1"),
                row.get("to", "main"),
                row.get("kind", "needs-user"),
                row.get("text", ""),
                row.get("notes"),
                "2026-10-24T00:00:00Z",
            )
        )


def git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - test runs fixed Git operations in a temp repo
        ["git", "-C", str(repo), *args],  # noqa: S607 - fixed system git executable
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "file").write_text("base")
    git(repo, "add", "file")
    git(repo, "commit", "-m", "base")
    return repo


def test_is_merged_detects_ancestor_and_unmerged_branch(tmp_path):
    repo = repository(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "branch", "landed", base)
    git(repo, "checkout", "-b", "worktree/plan-a")
    (repo / "file").write_text("branch")
    git(repo, "commit", "-am", "branch change")
    assert not is_merged(repo, "worktree/plan-a")
    git(repo, "checkout", "main")
    git(repo, "merge", "--ff-only", "worktree/plan-a")
    assert is_merged(repo, "worktree/plan-a")


def test_missing_ref_is_not_merged(tmp_path):
    repo = repository(tmp_path)
    assert not is_merged(repo, "worktree/missing")


def test_approved_unmerged_branch_emits_blocked_event_until_merged(tmp_path):
    repo = repository(tmp_path)
    git(repo, "checkout", "-b", "worktree/plan-a")
    (repo / "file").write_text("branch")
    git(repo, "commit", "-am", "branch change")
    now = datetime.now(UTC)
    approved = (now - timedelta(minutes=20)).isoformat()
    record = {
        "id": "plan-a",
        "status": "active",
        "branch": "worktree/plan-a",
        "merge_approved_at": approved,
    }

    detail = approved_merge_detail(record, repo, now.timestamp())
    assert detail == "approved 20m ago, not in main"
    events, _ = frame_events(
        [
            {
                "id": "plan-a",
                "state": "blocked",
                "detail": detail,
                "newest_activity": now.timestamp(),
            }
        ],
        now.timestamp(),
        1200,
    )
    assert events[0].kind == "blocked"
    assert events[0].detail == detail

    git(repo, "checkout", "main")
    git(repo, "merge", "--ff-only", "worktree/plan-a")
    assert approved_merge_detail(record, repo, now.timestamp()) is None


def test_approved_plan_with_missing_branch_is_unknown(tmp_path):
    repo = repository(tmp_path)
    record = {
        "id": "plan-a",
        "status": "active",
        "merge_approved_at": "2026-10-22T10:00:00Z",
    }

    assert approved_merge_detail(record, repo, 1_792_667_200.0) is None


def test_approve_merge_is_idempotent():
    original = b"---\ntype: plan\n---\n"
    approved = approve_line(original, "2026-10-22T10:00:00+00:00")
    assert b"merge_approved_at: 2026-10-22T10:00:00+00:00" in approved
    assert approve_line(approved, "2026-10-22T11:00:00+00:00") == approved


def test_plan_schema_accepts_assignment_and_merge_approval_fields(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text(
        "---\ntype: plan\nid: sample\nstatus: active\n"
        "assigned_to: orchestrator-2\n"
        "merge_approved_at: '2026-10-22T10:00:00Z'\n---\n"
        "## Acceptance criteria\n\n- merged\n"
    )

    assert inspect(plan).artifact_type == "plan"


def test_awaiting_user_requires_unanswered_message_and_uses_decision_title(tmp_path):
    decision = tmp_path / "decision.json"
    decision.write_text('{"title":"Approve this change"}', encoding="utf-8")
    messages = [
        {
            "from": "orchestrator-1",
            "to": "main",
            "kind": "needs-user",
            "text": "Please approve",
            "notes": str(decision),
        },
    ]
    record = {"id": "plan-a", "assigned_to": "orchestrator-1", "status": "active"}
    _write_messages(tmp_path, messages)

    assert awaiting_user_message(record, messages) == messages[0]
    assert awaiting_user(record, tmp_path) == "Approve this change"
    assert (
        awaiting_user_message(
            record,
            [*messages, {"from": "main", "to": "orchestrator-1", "kind": "info"}],
        )
        is None
    )


def test_awaiting_merge_ready_clears_after_dashboard_reply():
    record = {"assigned_to": "orchestrator-1", "status": "active"}
    messages = [
        {"from": "orchestrator-1", "to": "main", "kind": "merge-ready"},
        {"from": "dashboard", "to": "orchestrator-1", "kind": "info"},
    ]

    assert awaiting_user_message(record, messages) is None


def test_awaiting_user_ignores_unassigned_and_terminal_plans(tmp_path):
    _write_messages(
        tmp_path,
        [
            {
                "from": "orchestrator-1",
                "to": "main",
                "kind": "needs-user",
                "text": "approve",
            }
        ],
    )

    assert awaiting_user({"status": "active"}, tmp_path) is None
    assert (
        awaiting_user(
            {"assigned_to": "orchestrator-1", "status": "completed"}, tmp_path
        )
        is None
    )


def test_awaiting_user_falls_back_to_text_and_skips_malformed_lines(tmp_path):
    _write_messages(
        tmp_path,
        [
            {
                "from": "orchestrator-1",
                "to": "main",
                "kind": "needs-user",
                "text": "Please approve",
            }
        ],
    )

    assert (
        awaiting_user({"assigned_to": "orchestrator-1", "status": "active"}, tmp_path)
        == "Please approve"
    )


def test_awaiting_user_falls_back_when_text_is_missing_or_empty(tmp_path):
    record = {"assigned_to": "orchestrator-1", "status": "active"}
    for text in (" ", " ", "  "):
        inbox = tmp_path / str(len(list(tmp_path.iterdir())))
        inbox.mkdir()
        _write_messages(
            inbox,
            [
                {
                    "from": "orchestrator-1",
                    "to": "main",
                    "kind": "needs-user",
                    "text": text,
                }
            ],
        )

        assert awaiting_user(record, inbox) == "Waiting on your decision"
