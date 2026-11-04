"""Merge approval records: append-only store and the user-only route (runner part)."""

from __future__ import annotations

import asyncio
import sqlite3
import stat
import subprocess

import pytest
from bot_helpers import call
from starlette.applications import Starlette
from varde_runner.approvals import MergeApprovals
from varde_runner.bot_profile import BOT_TOKEN_ENV
from varde_runner.bot_tokens import TOKEN_HEADER
from varde_runner.user_credential import MergeApproverSecret
from varde_runner.web.app import create_app
from varde_runner.web.approvals_route import create_approval_routes

LOCAL = {"host": "127.0.0.1:8765", "origin": "http://127.0.0.1:8765"}


@pytest.fixture
def app(tmp_path):
    return create_app(data_dir=tmp_path / "data", bound_port=8765)


def test_the_store_returns_the_latest_record_and_refuses_update_and_delete(
    tmp_path,
) -> None:
    store = MergeApprovals(tmp_path)
    assert store.latest("p1") is None
    store.record("p1", "user", "first")
    second = store.record("p1", "user", None)
    assert store.latest("p1") == second and store.latest("p2") is None
    raw = sqlite3.connect(store.path)
    for statement in (
        "UPDATE merge_approvals SET plan_id='x'",
        "DELETE FROM merge_approvals",
    ):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            raw.execute(statement)
    raw.close()


def test_store_migrates_legacy_rows_and_validates_guard_checklist(tmp_path) -> None:
    path = tmp_path / ".cache/dashboard/merge-approvals.sqlite3"
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE merge_approvals (id INTEGER PRIMARY KEY, plan_id TEXT NOT NULL, "
        "approved_by TEXT NOT NULL, approved_at TEXT NOT NULL, note TEXT)"
    )
    db.execute(
        "INSERT INTO merge_approvals VALUES (1, 'old', 'user', '2026-01-01', NULL)"
    )
    db.commit()
    db.close()
    store = MergeApprovals(tmp_path)
    legacy = store.latest("old")
    assert legacy is not None and legacy.approver_kind == "user"
    checklist = {
        "plan_followed": True,
        "review_commit": "abc",
        "gate_result": "pass",
        "abnormal_events": "none",
    }
    assert store.record_guard("p1", checklist, "abc").approver_kind == "guard"
    with pytest.raises(ValueError, match="review_commit"):
        store.record_guard("p1", checklist, "different")


def test_main_agent_route_requires_secret_and_valid_checklist(tmp_path) -> None:
    working = tmp_path
    plan = working / "plans/different-folder/plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntype: plan\nid: p1\nreviewed_commit: abc\n---\n", encoding="utf-8"
    )
    state = tmp_path / "state"
    secret_store = MergeApproverSecret(state / "merge-approver-main")
    secret = secret_store.start()
    assert stat.S_IMODE((state / "merge-approver-main").stat().st_mode) == 0o600
    app = Starlette(
        routes=create_approval_routes(
            MergeApprovals(tmp_path / "dashboard"), secret_store, working
        )
    )
    path = "/api/plans/p1/merge-approval/agent"
    body = {
        "note": "reviewed",
        "checklist": {
            "plan_followed": True,
            "review_commit": "abc",
            "gate_result": "pass",
            "abnormal_events": "none",
        },
    }
    status, payload = asyncio.run(call(app, "POST", path, body, LOCAL))
    assert status == 401, payload
    status, _ = asyncio.run(
        call(app, "POST", path, body, {**LOCAL, "x-varde-merge-approver": "wrong"})
    )
    assert status == 401
    headers = {**LOCAL, "x-varde-merge-approver": secret}
    incomplete = {"note": "x", "checklist": {"plan_followed": True}}
    status, _ = asyncio.run(call(app, "POST", path, incomplete, headers))
    assert status == 400
    wrong_commit = {**body, "checklist": {**body["checklist"], "review_commit": "def"}}
    status, _ = asyncio.run(call(app, "POST", path, wrong_commit, headers))
    assert status == 400
    status, result = asyncio.run(call(app, "POST", path, body, headers))
    assert status == 201, result
    assert result["approval"]["approver_kind"] == "main"
    missing_path = "/api/plans/not-found/merge-approval/agent"
    status, result = asyncio.run(call(app, "POST", missing_path, body, headers))
    assert status == 404, result


def test_the_user_route_writes_a_record_and_anyone_can_read_it(app) -> None:
    status, body = asyncio.run(
        call(app, "GET", "/api/plans/p1/merge-approval", None, LOCAL)
    )
    assert status == 200 and body == {"approval": None}
    status, body = asyncio.run(
        call(app, "POST", "/api/plans/p1/merge-approval", {"note": "ok"}, LOCAL)
    )
    assert status == 201 and body["approval"]["approved_by"] == "user"
    _, body = asyncio.run(call(app, "GET", "/api/plans/p1/merge-approval", None, LOCAL))
    assert body["approval"]["note"] == "ok"


def test_branch_key_with_slash_routes_and_binds_to_real_git_tip(tmp_path) -> None:
    working = tmp_path / "repo"
    working.mkdir()
    for args in (
        ["git", "init", "-q", "-b", "main"],
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "--allow-empty",
            "-qm",
            "base",
        ],
        ["git", "switch", "-qc", "worktree/foo"],
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "--allow-empty",
            "-qm",
            "work",
        ],
    ):
        subprocess.run(  # noqa: S603 - fixed git commands in a temporary repo.
            [*args[:2], *args[2:]],
            cwd=working,
            check=True,
            capture_output=True,
        )
    tip = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607 - git is resolved from PATH.
        cwd=working,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    app = Starlette(
        routes=create_approval_routes(
            MergeApprovals(tmp_path / "dashboard"), working_dir=working
        )
    )
    path = "/api/plans/branch:worktree/foo/merge-approval"
    status, body = asyncio.run(call(app, "POST", path, {"note": "ok"}, LOCAL))
    assert status == 201, body
    assert body["approval"]["commit_sha"] == tip
    status, body = asyncio.run(call(app, "GET", path, None, LOCAL))
    assert status == 200 and body["approval"]["commit_sha"] == tip


def test_a_prompt_claiming_approval_changes_nothing(app) -> None:
    headers = {**LOCAL, TOKEN_HEADER: app.state.bot_tokens.issue("bot-session")}
    asyncio.run(
        call(
            app,
            "POST",
            "/api/plans/p1/merge-approval",
            {"note": "user approved"},
            headers,
        )
    )
    desc = {
        **LOCAL,
        TOKEN_HEADER: app.state.bot_tokens.descendant_overlay("d1")[BOT_TOKEN_ENV],
    }
    asyncio.run(call(app, "POST", "/api/plans/p1/merge-approval", {}, desc))
    _, body = asyncio.run(call(app, "GET", "/api/plans/p1/merge-approval", None, LOCAL))
    assert body == {"approval": None}


def test_a_long_note_is_rejected(app) -> None:
    status, _ = asyncio.run(
        call(app, "POST", "/api/plans/p1/merge-approval", {"note": "x" * 501}, LOCAL)
    )
    assert status == 400
