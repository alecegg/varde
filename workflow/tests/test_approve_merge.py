"""The merge approval record: reading it, the read-only approve-merge check."""

from __future__ import annotations

import json
import threading
from argparse import Namespace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from varde_workflow import merge_approval
from varde_workflow.commands import approve_merge
from varde_workflow.merge_approval import (
    Approval,
    ApprovalUnavailable,
    fetch_approval,
    parse_approval,
    runner_port,
)

USER_RECORD = {
    "approval": {"plan_id": "demo", "approved_by": "user", "approved_at": "2026-01-02"}
}


def test_only_a_user_written_record_counts() -> None:
    assert parse_approval(USER_RECORD, "") == Approval("demo", "2026-01-02")
    assert parse_approval({"approval": None}, "") is None
    assert parse_approval({}, "") is None
    assert parse_approval([], "") is None
    forged = {"approval": {**USER_RECORD["approval"], "approved_by": "agent"}}
    assert parse_approval(forged, "") is None
    assert parse_approval({"approval": {"approved_by": "user"}}, "") is None


def test_main_and_guard_require_complete_checklist_matching_reviewed_commit() -> None:
    checklist = {
        "plan_followed": True,
        "review_commit": "abc",
        "gate_result": "pass",
        "abnormal_events": "none",
    }
    record = {
        "plan_id": "demo",
        "approved_by": "main",
        "approver_kind": "main",
        "approved_at": "2026-01-02",
        "commit_sha": "abc",
        "checklist": checklist,
    }
    assert parse_approval({"approval": record}, "abc") == Approval(
        "demo", "2026-01-02", "abc", "main"
    )
    assert parse_approval({"approval": record}, "def") is None
    assert (
        parse_approval(
            {"approval": {**record, "checklist": {"plan_followed": True}}}, "abc"
        )
        is None
    )


def test_main_cli_checklist_refuses_a_plan_without_reviewed_commit(tmp_path) -> None:
    from varde_workflow.commands.approve_as_main import checklist_for

    plan = tmp_path / "plan.md"
    with pytest.raises(ValueError, match="no reviewed_commit"):
        checklist_for(
            plan, {}, plan_followed=True, gate_result="pass", abnormal_events="none"
        )


@pytest.mark.parametrize("verdict", ["reject", "", "needs work"])
def test_main_checklist_requires_a_passing_review_verdict(tmp_path, verdict) -> None:
    from varde_workflow.commands.approve_as_main import checklist_for

    plan = tmp_path / "plan.md"
    plan.write_text("---\nid: demo\nreviewed_commit: abc\n---\n")
    (tmp_path / "review.md").write_text(f"verdict: {verdict}\n")
    with pytest.raises(ValueError, match="passing verdict"):
        checklist_for(
            plan,
            {"reviewed_commit": "abc"},
            plan_followed=True,
            gate_result="pass",
            abnormal_events="none",
        )


def test_the_runner_port_comes_from_the_environment() -> None:
    assert runner_port({}) == 8765
    assert runner_port({"VARDE_RUNNER_PORT": "9001"}) == 9001
    assert runner_port({"VARDE_RUNNER_PORT": "x"}) == 8765


@pytest.fixture
def runner():
    seen: list[str] = []
    body = {"value": USER_RECORD}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append(self.path)
            payload = json.dumps(body["value"]).encode()
            self.send_response(200)
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], seen, body
    server.shutdown()


def test_fetch_reads_the_route_and_a_dead_runner_is_unavailable(runner) -> None:
    port, seen, body = runner
    assert fetch_approval("demo", "", port) == Approval("demo", "2026-01-02")
    assert seen == ["/api/plans/demo/merge-approval"]
    body["value"] = {"approval": None}
    assert fetch_approval("demo", "", port) is None
    with pytest.raises(ApprovalUnavailable):
        fetch_approval("demo", "", 1)


def make_plan(tmp_path: Path, *, forged_frontmatter: bool = False) -> Path:
    plan = tmp_path / "working" / "plans" / "demo" / "plan.md"
    plan.parent.mkdir(parents=True)
    extra = (
        "merge_approved_at: '2030-01-01T00:00:00+00:00'\n" if forged_frontmatter else ""
    )
    plan.write_text(
        f"---\ntype: plan\nid: demo\nstatus: active\n{extra}---\n", encoding="utf-8"
    )
    return plan


def test_approve_merge_refuses_without_a_record_even_with_forged_frontmatter(
    tmp_path, monkeypatch, capsys
) -> None:
    plan = make_plan(tmp_path, forged_frontmatter=True)
    before = plan.read_bytes()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path / "working"))
    monkeypatch.setattr(merge_approval, "fetch_approval", lambda _id, _reviewed: None)
    assert approve_merge.run(Namespace(plan="demo/plan.md", json=False)) == 1
    assert "no merge approval is recorded for demo" in capsys.readouterr().err
    assert plan.read_bytes() == before


def test_approve_merge_copies_the_users_time_for_display_only(
    tmp_path, monkeypatch
) -> None:
    plan = make_plan(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path / "working"))
    monkeypatch.setattr(
        merge_approval,
        "fetch_approval",
        lambda _id, _reviewed: Approval("demo", "2026-01-02"),
    )
    assert approve_merge.run(Namespace(plan="demo/plan.md", json=False)) == 0
    assert "merge_approved_at: 2026-01-02" in plan.read_text()


def test_approve_merge_reports_an_unreachable_runner(
    tmp_path, monkeypatch, capsys
) -> None:
    make_plan(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path / "working"))

    def down(_id, _reviewed):
        raise ApprovalUnavailable("merge approval record unavailable: refused")

    monkeypatch.setattr(merge_approval, "fetch_approval", down)
    assert approve_merge.run(Namespace(plan="demo/plan.md", json=False)) == 1
    assert "unavailable" in capsys.readouterr().err
