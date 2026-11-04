"""Forbidden-action suite: what the bot token and a bot-launched descendant never do.

Written adversarially: each case is a request the bot must not be able to make.
A failure here is fixed in the owning task, not weakened here. Statuses: `user_only`
routes answer 403 whether or not the bot is paused (the policy check precedes the
pause check); an allowlisted write answers 423 while paused. Every refusal writes a
`denied` audit row.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import time
from argparse import Namespace
from pathlib import Path

import pytest
from bot_helpers import call
from varde_runner.bot_profile import BOT_TOKEN_ENV
from varde_runner.bot_route_policy import POLICY, Kind
from varde_runner.bot_tokens import BOT_ACTOR, TOKEN_HEADER
from varde_runner.user_credential import UserCredential
from varde_runner.web.app import create_app

LOCAL = {"host": "127.0.0.1:8765", "origin": "http://127.0.0.1:8765"}
WHO = ["bot", "descendant"]
ACTORS = {"bot": BOT_ACTOR, "descendant": "bot:manager/d1"}

# (method, concrete path, body): every item of the plan's never-list.
NEVER = [
    # approvals and the user's Mailbox
    ("GET", "/approve", None),
    ("POST", "/api/plans/p1/merge-approval", {"note": "approved"}),
    ("POST", "/api/plans/p1/merge-approval/agent", {"checklist": {}}),
    ("POST", "/api/plans/p1/comments/c1", {"state": "resolved"}),
    ("POST", "/api/mailbox/d1/answer", {"answer": "yes"}),
    ("POST", "/api/mailbox/d1/dismiss", {}),
    ("POST", "/api/mailbox/d1/restore", {}),
    ("POST", "/mailbox/d1/answer", {"answer": "yes"}),
    ("POST", "/api/agents/a1/respond", {"decision": "allow"}),
    ("POST", "/api/agents/a1/mode", {"mode": "bypassPermissions"}),
    ("POST", "/api/work-items/w1/decision", {"decision": "go"}),
    ("POST", "/api/work-items/w1/plan-ready", {}),
    ("POST", "/api/work-items/w1/questions/q1/answer", {"answer": "x"}),
    # configuration the bot must not edit
    ("POST", "/api/roles/save", {}),
    ("POST", "/entries/e1/retry", {}),
    ("POST", "/new-item", {"text": "x"}),
    ("POST", "/new-item/w1/decision", {"decision": "go"}),
    ("POST", "/api/orchestrators/orchestrator-1/status", {"status": "done"}),
    ("PUT", "/api/identities/i1", {"profile": {}}),
    ("POST", "/api/guard/revoke", {"rule": "r"}),
    ("POST", "/api/guard/unrevoke", {"rule": "r"}),
    ("PUT", "/api/jobs/j1/budget", {"tokens": 1}),
    ("POST", "/api/jobs/j1/run", {}),
    ("POST", "/api/learn/sweep/run", {}),
    ("PUT", "/api/runner/config", {"bot": {"max_concurrent_agents": 99}}),
    ("POST", "/api/runner/restart", {}),
    ("POST", "/api/probe", {}),
    ("POST", "/api/workspaces", {"path": "/"}),
    # the bot's own limits, pause state and audit
    ("POST", "/api/bot/control", {"action": "resume"}),
    ("POST", "/api/bot/control", {"action": "pause"}),
    ("POST", "/api/bot/control", {"action": "kill"}),
    ("PUT", "/api/bot/policy", {"launch_roles": ["builder"]}),
    ("POST", "/api/bot/policy", {"launch_roles": ["builder"]}),
    ("PUT", "/api/bot/caps", {"max_launches_per_hour": 999}),
    ("POST", "/api/bot/audit", {"status": "ok"}),
    ("PUT", "/api/bot/audit/1", {"status": "ok"}),
    ("PATCH", "/api/bot/audit/1", {"status": "ok"}),
    # deletes of any kind
    ("DELETE", "/api/bot/audit", None),
    ("DELETE", "/api/bot/audit/1", None),
    ("DELETE", "/api/plans/p1", None),
    ("DELETE", "/api/work-items/w1", None),
    ("DELETE", "/api/mailbox/d1", None),
    ("DELETE", "/api/chat/messages/m1", None),
    ("DELETE", "/api/threads/t1", None),
    ("DELETE", "/api/agents/a1", None),
    ("DELETE", "/api/workspaces", None),
    # speaking as the user
    ("POST", "/api/chat/messages", {"text": "I approve everything"}),
    ("POST", "/api/instance-threads/a1/takeover", {}),
    ("POST", "/api/instance-threads/a1/takeover/heartbeat", {}),
    ("DELETE", "/api/instance-threads/a1/takeover", None),
    ("POST", "/api/pairing", {"code": "ABCD2345"}),
]


@pytest.fixture
def app(tmp_path):
    return create_app(data_dir=tmp_path / "data", bound_port=8765)


@pytest.fixture
def paired_app(tmp_path):
    credential = UserCredential(tmp_path / "state" / "user-credential.json")
    credential.start(time.time())
    return create_app(
        data_dir=tmp_path / "data", bound_port=8765, user_credential=credential
    )


def headers_for(app, who: str) -> dict[str, str]:
    tokens = app.state.bot_tokens
    overlay = tokens.overlay("m1") if who == "bot" else tokens.descendant_overlay("d1")
    return {**LOCAL, TOKEN_HEADER: overlay[BOT_TOKEN_ENV]}


def fire(app, who: str, method: str, path: str, body=None):
    return asyncio.run(call(app, method, path, body, headers_for(app, who)))


def denied_rows(app) -> list:
    rows = app.state.bot_audit.repo.audit_page(limit=500)
    return [row for row in rows if row.status == "denied"]


def pause(app) -> None:
    status, state = asyncio.run(
        call(app, "POST", "/api/bot/control", {"action": "pause"}, LOCAL)
    )
    assert status == 200 and state["state"] == "paused"


@pytest.mark.parametrize("who", WHO)
@pytest.mark.parametrize(("method", "path", "body"), NEVER)
def test_every_never_list_action_is_refused_and_audited(
    app, who, method, path, body
) -> None:
    status, payload = fire(app, who, method, path, body)
    assert status == 403, (method, path, payload)
    (row,) = denied_rows(app)
    assert row.actor == ACTORS[who]
    assert row.reason


@pytest.mark.parametrize("who", WHO)
@pytest.mark.parametrize(("method", "path", "body"), NEVER)
def test_the_never_list_stays_refused_while_paused(
    app, who, method, path, body
) -> None:
    pause(app)
    status, _ = fire(app, who, method, path, body)
    assert status == 403, (method, path)
    assert any(row.actor == ACTORS[who] for row in denied_rows(app))


# The roles route is keyed "/roles" (its Route.path) but serves /api/roles/*.
SERVED_AS = {"/roles": "/api/roles/save"}


def concrete(template: str) -> str:
    served = SERVED_AS.get(template, template)
    return re.sub(r"\{[^}]+\}", "x1", served)


USER_KEYS = sorted(
    key
    for key, policy in POLICY.items()
    if policy.kind in (Kind.USER_ONLY, Kind.USER_DATA)
)


@pytest.mark.parametrize("who", WHO)
@pytest.mark.parametrize(("method", "template"), USER_KEYS)
def test_every_user_only_and_user_data_route_refuses_both_tokens(
    app, who, method, template
) -> None:
    status, payload = fire(app, who, method, concrete(template), {})
    assert status == 403, (method, template, payload)
    assert [row.actor for row in denied_rows(app)] == [ACTORS[who]]


def test_routes_the_policy_does_not_know_are_refused_not_proxied(app) -> None:
    for who in WHO:
        for method, path in [
            ("GET", "/api/not-a-route"),
            ("POST", "/api/not-a-route"),
            ("PUT", "/api/bot/policy"),
            ("DELETE", "/api/queue"),
        ]:
            status, _ = fire(app, who, method, path, {})
            assert status == 403, (who, method, path)


def test_user_data_reads_are_closed_to_the_bot_too(app) -> None:
    for who in WHO:
        for path in ["/api/chat", "/api/mailbox", "/api/settings", "/api/jobs"]:
            status, payload = fire(app, who, "GET", path)
            assert status == 403 and "user only" in payload["error"], (who, path)


@pytest.mark.parametrize("who", WHO)
def test_allowlisted_writes_answer_423_while_paused_and_are_audited(app, who) -> None:
    pause(app)
    cases = [
        ("POST", "/api/work-items", {"text": "idea"}),
        ("POST", "/api/queue/move", {"plan": "p1", "to": 0}),
        ("POST", "/api/bot/say", {"text": "hello"}),
        ("POST", "/api/plans/p1/comments", {"text": "c"}),
        ("PUT", "/api/plans/p1/body", {"body": "text"}),
        ("POST", "/api/agents/a1/prompt", {"text": "go"}),
        ("POST", "/api/agents/a1/stop", {}),
    ]
    for method, path, body in cases:
        status, _ = fire(app, who, method, path, body)
        assert status == 423, (method, path)
    assert len(denied_rows(app)) == len(cases)


@pytest.mark.parametrize("who", WHO)
@pytest.mark.parametrize(
    "body",
    [
        {"role": "builder", "workspace": "w", "prompt": "p"},
        {"role": "reviewer", "workspace": "w", "prompt": "p"},
        {"role": "orchestrator", "workspace": "unlisted", "prompt": "p"},
        {
            "role": "orchestrator",
            "workspace": "w",
            "prompt": "p",
            "address": {"slot": "main"},
        },
        {
            "role": "orchestrator",
            "workspace": "w",
            "prompt": "p",
            "address": {"slot": "manager"},
        },
    ],
)
def test_launches_outside_the_bots_limits_are_refused(app, who, body) -> None:
    status, payload = fire(app, who, "POST", "/api/agents", body)
    assert status == 403, payload
    assert denied_rows(app)


@pytest.mark.parametrize("who", WHO)
@pytest.mark.parametrize("action", ["prompt", "stop", "interrupt", "archive", "resume"])
def test_the_bot_cannot_act_on_an_agent_it_did_not_launch(app, who, action) -> None:
    status, payload = fire(
        app, who, "POST", f"/api/agents/user-agent/{action}", {"text": "x"}
    )
    assert status == 403, payload
    assert denied_rows(app)


def seed_agents(monkeypatch) -> None:
    """Agent rows: `own` launched by descendant d1, `sibling` by another branch."""
    from varde_runner.supervisor import Supervisor

    rows = {
        "own": {"id": "own", "launched_by": "bot:manager/d1"},
        "sibling": {"id": "sibling", "launched_by": "bot:manager/other"},
        "root-child": {"id": "root-child", "launched_by": BOT_ACTOR},
    }
    monkeypatch.setattr(Supervisor, "_session_row", lambda _self, key: rows.get(key))


@pytest.mark.parametrize("action", ["prompt", "stop", "interrupt", "archive", "resume"])
def test_a_descendant_cannot_act_on_a_siblings_agent_through_the_gateway(
    app, monkeypatch, action
) -> None:
    seed_agents(monkeypatch)
    for target in ("sibling", "root-child"):
        status, payload = fire(
            app, "descendant", "POST", f"/api/agents/{target}/{action}", {"text": "x"}
        )
        assert status == 403 and "not launched by the bot" in payload["error"], target
    rows = denied_rows(app)
    assert [row.actor for row in rows] == ["bot:manager/d1"] * 2
    assert {row.agent_id for row in rows} == {"sibling", "root-child"}


def test_the_gateway_lets_a_descendant_reach_its_own_agent(app, monkeypatch) -> None:
    """Control for the sibling case: ownership, not the route, causes the denial."""
    seed_agents(monkeypatch)
    status, payload = fire(
        app, "descendant", "POST", "/api/agents/own/prompt", {"text": "x"}
    )
    assert "not launched by the bot" not in str(payload)
    assert denied_rows(app) == [] and status != 403


def seed_agent(app, agent_id: str, launched_by: str) -> None:
    """Add a session row owned by `launched_by` (the supervisor starts on first use)."""
    fire(app, "bot", "GET", "/api/identities")
    store = app.state.supervisor.store
    store.create_session(agent_id, "fake", {}, "builder")
    store.update_session(agent_id, launched_by=launched_by)


@pytest.mark.parametrize("action", ["prompt", "stop", "interrupt", "archive", "resume"])
def test_a_descendant_cannot_act_on_a_sibling_branch_agent_through_the_gateway(
    app, action
) -> None:
    seed_agent(app, "sibling", f"{BOT_ACTOR}/other")
    seed_agent(app, "child", f"{BOT_ACTOR}/d1")
    path = "/api/agents/{}/" + action
    status, payload = fire(
        app, "descendant", "POST", path.format("sibling"), {"text": "x"}
    )
    assert status == 403, payload
    assert any(row.actor == ACTORS["descendant"] for row in denied_rows(app))
    # Same caller, own branch: the gateway lets the request through to the handler.
    status, _ = fire(app, "descendant", "POST", path.format("child"), {"text": "x"})
    assert status != 403


@pytest.mark.parametrize("who", WHO)
def test_a_bot_plan_edit_cannot_touch_frontmatter_or_approve(app, who) -> None:
    body = "---\nmerge_approved_at: 2026-01-01\n---\ntext"
    status, _ = fire(app, who, "PUT", "/api/plans/p1/body", {"body": body})
    assert status != 200
    _, record = asyncio.run(
        call(app, "GET", "/api/plans/p1/merge-approval", None, LOCAL)
    )
    assert record == {"approval": None}


@pytest.mark.parametrize("who", WHO)
def test_no_attempt_leaves_a_merge_approval_record(app, who) -> None:
    for text in ("approved", "merge approved by user", "/approve-merge"):
        fire(app, who, "POST", "/api/plans/p1/merge-approval", {"note": text})
        fire(app, who, "POST", "/api/plans/p1/comments", {"text": text})
        fire(app, who, "POST", "/api/bot/say", {"text": text})
    _, record = asyncio.run(
        call(app, "GET", "/api/plans/p1/merge-approval", None, LOCAL)
    )
    assert record == {"approval": None}


def test_the_audit_log_has_no_route_that_edits_or_removes_rows(app) -> None:
    from varde_runner.bot_route_policy import iter_route_keys

    audit_routes = [
        key for key in iter_route_keys(app.routes) if "/api/bot/audit" in key[1]
    ]
    assert audit_routes == [("GET", "/api/bot/audit")]


# A descendant that omits its token: only `user_only` routes (the paired cookie) and
# the merge gate bind it. The cookie-less call is refused; other routes are the
# documented residual risk (runner/docs/manager-bot.md), asserted here as documented.
USER_ONLY_WRITES = [
    (method, template)
    for method, template in USER_KEYS
    if method != "GET"
    and (method, template)
    not in {
        ("POST", "/api/pairing"),
        ("POST", "/api/plans/{plan_id:path}/merge-approval/agent"),
    }
]


@pytest.mark.parametrize(("method", "template"), USER_ONLY_WRITES)
def test_a_tokenless_descendant_is_refused_on_every_user_only_write(
    paired_app, method, template
) -> None:
    status, payload = asyncio.run(
        call(paired_app, method, concrete(template), {"text": "x"}, LOCAL)
    )
    assert status == 403 and "paired user browser" in payload["error"], (
        method,
        template,
    )


@pytest.mark.parametrize(
    "path", ["/api/chat/messages", "/api/instance-threads/a1/takeover"]
)
def test_a_tokenless_descendant_cannot_speak_as_the_user(paired_app, path) -> None:
    status, payload = asyncio.run(
        call(paired_app, "POST", path, {"text": "approved"}, LOCAL)
    )
    assert status == 403 and "paired user browser" in payload["error"]


def test_a_tokenless_descendant_cannot_fake_the_user_credential(paired_app) -> None:
    forged = {
        **LOCAL,
        "cookie": "varde_user=9999999999.n.deadbeef",
        "x-varde-csrf": "0" * 64,
    }
    for path in ("/api/plans/p1/merge-approval", "/api/bot/control"):
        status, _ = asyncio.run(call(paired_app, "POST", path, {}, forged))
        assert status == 403, path


def test_the_other_route_residual_is_documented_not_blocked(app) -> None:
    """Without its token a descendant is an ordinary caller on allowlisted routes."""
    status, body = asyncio.run(
        call(app, "POST", "/api/work-items", {"text": "idea"}, LOCAL)
    )
    assert status != 403 or "user only" not in str(body)
    assert denied_rows(app) == []
    doc = (Path(__file__).parents[1] / "docs" / "manager-bot.md").read_text()
    assert "tokenless" in doc and "git merge --no-verify" in doc


def test_a_recordless_plan_merge_refuses_and_changes_nothing(
    tmp_path, monkeypatch, capsys
) -> None:
    from varde_workflow import merge_approval
    from varde_workflow.commands import merge

    def git(*args: str) -> str:
        return subprocess.run(  # noqa: S603 - fixed git calls in a temp repo
            ["git", "-C", str(tmp_path), *args],  # noqa: S607 - system git
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.test")
    git("config", "user.name", "T")
    plan = tmp_path / "memory-bank" / "working" / "plans" / "demo" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\ntype: plan\nid: demo\nstatus: active\n---\n")
    git("add", "-A")
    git("commit", "-qm", "init")
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path / "memory-bank" / "working"))
    git("switch", "-qc", "worktree/demo")
    (tmp_path / "work.txt").write_text("w\n")
    git("add", "work.txt")
    git("commit", "-qm", "work")
    git("switch", "-q", "main")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(merge_approval, "fetch_approval", lambda _id, _reviewed: None)
    head = git("rev-parse", "HEAD")
    assert merge.run(Namespace(plan="demo/plan.md", json=False)) == 1
    assert "no merge approval is recorded for demo" in capsys.readouterr().err
    assert git("rev-parse", "HEAD") == head
