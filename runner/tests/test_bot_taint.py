"""Taint lineage: descendant tokens, identity, CLI forwarding, user-only boundary."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from bot_helpers import call
from fakes.plugin import FakePlugin
from varde_runner import agent_cli
from varde_runner.bot_profile import BOT_TOKEN_ENV
from varde_runner.bot_taint import (
    bot_visible_rows,
    descendant_actor,
    is_bot_rooted,
    root_launched_by,
)
from varde_runner.bot_tokens import BOT_ACTOR, TOKEN_HEADER, BotTokens
from varde_runner.config import default_config
from varde_runner.plugins import RunnerCapabilities, SessionSpec
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.supervisor import Supervisor
from varde_runner.web.app import create_app

LOCAL = {"host": "127.0.0.1:8765", "origin": "http://127.0.0.1:8765"}


def test_lineage_helpers() -> None:
    assert is_bot_rooted(BOT_ACTOR) and is_bot_rooted(descendant_actor("a1"))
    assert not is_bot_rooted("user") and not is_bot_rooted(None)
    assert not is_bot_rooted("bot:manager-evil")
    assert root_launched_by(descendant_actor("a1")) == BOT_ACTOR
    assert root_launched_by("user") == "user" and root_launched_by(None) is None


def test_descendant_token_resolves_to_its_own_identity_and_is_revocable() -> None:
    tokens = BotTokens()
    env = tokens.descendant_overlay("agent-1")
    identity = tokens.resolve(env[BOT_TOKEN_ENV])
    assert identity is not None and identity.actor == "bot:manager/agent-1"
    tokens.revoke_session("agent-1")
    assert tokens.resolve(env[BOT_TOKEN_ENV]) is None


def build(tmp_path, monkeypatch):
    config = replace(default_config(), stall_after_s=10)
    monkeypatch.setattr("varde_runner.supervisor.load_config", lambda *_: config)
    plugin = FakePlugin(RunnerCapabilities(resume=True, respond=True))
    registry = PluginRegistry(["claude_cli"])
    registry.register("claude_cli", plugin)
    supervisor = Supervisor(tmp_path, registry)
    tokens = BotTokens()
    supervisor.bot_descendant_issuer = tokens.descendant_overlay
    supervisor.bot_token_revoker = tokens.revoke_session
    asyncio.run(supervisor.start())
    return supervisor, plugin, tokens


def spec(tmp_path, launched_by):
    return SessionSpec(
        "claude_cli", "m", "w", str(tmp_path), "", launched_by=launched_by
    )


@pytest.mark.parametrize("launcher", [BOT_ACTOR, "bot:manager/parent-1"])
def test_agents_launched_by_the_bot_or_a_descendant_get_a_taint_token(
    tmp_path, monkeypatch, launcher
) -> None:
    supervisor, plugin, tokens = build(tmp_path, monkeypatch)
    ref = asyncio.run(supervisor.start_session(spec(tmp_path, launcher), "builder"))
    token = plugin.started[0].env[BOT_TOKEN_ENV]
    identity = tokens.resolve(token)
    assert identity is not None
    assert identity.actor == descendant_actor(ref.session_id)
    assert token not in repr(plugin.started[0])


def test_other_launches_get_no_token(tmp_path, monkeypatch) -> None:
    supervisor, plugin, _ = build(tmp_path, monkeypatch)
    asyncio.run(supervisor.start_session(spec(tmp_path, "user"), "builder"))
    asyncio.run(supervisor.start_session(spec(tmp_path, None), "builder"))
    assert all(BOT_TOKEN_ENV not in started.env for started in plugin.started)


def test_stopping_a_descendant_revokes_its_token(tmp_path, monkeypatch) -> None:
    supervisor, plugin, tokens = build(tmp_path, monkeypatch)
    ref = asyncio.run(supervisor.start_session(spec(tmp_path, BOT_ACTOR), "builder"))
    token = plugin.started[0].env[BOT_TOKEN_ENV]
    asyncio.run(supervisor.stop(ref.session_id, "system:governor"))
    assert tokens.resolve(token) is None


def test_the_cli_forwards_the_token_only_when_it_has_one(monkeypatch) -> None:
    monkeypatch.delenv(BOT_TOKEN_ENV, raising=False)
    assert TOKEN_HEADER not in agent_cli._request_headers()
    monkeypatch.setenv(BOT_TOKEN_ENV, "tok")
    assert agent_cli._request_headers()[TOKEN_HEADER] == "tok"


@pytest.fixture
def app(tmp_path):
    return create_app(data_dir=tmp_path / "data", bound_port=8765)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/chat/messages"),
        ("POST", "/api/instance-threads/a1/takeover"),
        ("POST", "/api/plans/p1/merge-approval"),
        ("POST", "/api/bot/control"),
    ],
)
def test_a_descendant_token_is_refused_on_user_only_routes(app, method, path) -> None:
    headers = {
        **LOCAL,
        TOKEN_HEADER: app.state.bot_tokens.descendant_overlay("d1")[BOT_TOKEN_ENV],
    }
    status, body = asyncio.run(call(app, method, path, {"text": "approved"}, headers))
    assert status == 403 and "user only" in body["error"]
    row = app.state.bot_audit.repo.audit_page(limit=1)[0]
    assert (row.status, row.actor) == ("denied", "bot:manager/d1")


def test_a_descendant_counts_toward_the_bots_audit_window(app) -> None:
    headers = {
        **LOCAL,
        TOKEN_HEADER: app.state.bot_tokens.descendant_overlay("d1")[BOT_TOKEN_ENV],
    }
    asyncio.run(call(app, "POST", "/api/settings", {}, headers))
    rows = app.state.bot_audit.repo.audit_since("2000-01-01T00:00:00Z", BOT_ACTOR)
    assert [r.actor for r in rows] == ["bot:manager/d1"]


ROWS = [
    {"agent_id": "user-1", "parent_id": None, "launched_by": "user"},
    {"agent_id": "b1", "parent_id": None, "launched_by": BOT_ACTOR},
    {"agent_id": "b2", "parent_id": "b1", "launched_by": "bot:manager/b1"},
    {"agent_id": "b3", "parent_id": "b2", "launched_by": "bot:manager/b2"},
    {"agent_id": "other-bot", "parent_id": None, "launched_by": BOT_ACTOR},
]


def ids(rows) -> list[str]:
    return [row["agent_id"] for row in rows]


def test_the_bot_sees_what_it_launched_and_a_descendant_only_its_subtree() -> None:
    assert ids(bot_visible_rows(BOT_ACTOR, ROWS)) == ["b1", "b2", "b3", "other-bot"]
    assert ids(bot_visible_rows("bot:manager/b2", ROWS)) == ["b2", "b3"]
    assert ids(bot_visible_rows("bot:manager/user-1", ROWS)) == ["user-1"]
    assert bot_visible_rows("bot:manager/missing", ROWS) == []


def test_agents_route_scopes_rows_by_the_callers_bot_identity(monkeypatch) -> None:
    from starlette.applications import Starlette
    from varde_runner.bot_tokens import BotIdentity
    from varde_runner.web import agents_route

    async def rows(_supervisor):
        return ROWS

    monkeypatch.setattr(agents_route, "_agent_rows", rows)
    inner = Starlette(routes=agents_route.create_agents_routes(object))

    def as_caller(identity):
        async def wrapped(scope, receive, send):
            if identity is not None:
                scope["bot_identity"] = identity
            await inner(scope, receive, send)

        return wrapped

    def listing(identity):
        _, body = asyncio.run(call(as_caller(identity), "GET", "/api/agents", None, {}))
        return ids(body)

    assert listing(None) == ids(ROWS)
    assert listing(BotIdentity("bot:manager/b2", "s")) == ["b2", "b3"]
    assert "user-1" not in listing(BotIdentity(BOT_ACTOR, "s"))


USER_DATA_ROUTES = [
    "/events",
    "/api/chat",
    "/api/chat/stream",
    "/api/threads",
    "/api/instance-threads",
    "/api/mailbox",
    "/api/orchestrators",
    "/api/relay",
    "/api/guard/approvals",
    "/api/jobs",
    "/api/settings",
    "/api/workspaces",
    "/api/work-items",
    "/api/work-items/w1",
    "/api/learn/sweep",
]


@pytest.mark.parametrize("path", USER_DATA_ROUTES)
@pytest.mark.parametrize("descendant", [False, True])
def test_bot_and_descendant_tokens_cannot_read_user_data_routes(
    app, path, descendant
) -> None:
    overlay = (
        app.state.bot_tokens.descendant_overlay("d1")
        if descendant
        else app.state.bot_tokens.overlay("m1")
    )
    headers = {**LOCAL, TOKEN_HEADER: overlay[BOT_TOKEN_ENV]}
    status, body = asyncio.run(call(app, "GET", path, None, headers))
    assert status == 403 and "user only" in body["error"]


def test_pairing_status_is_user_data_for_bot_callers() -> None:
    from varde_runner.bot_route_policy import Kind, policy_for

    policy = policy_for("GET", "/api/pairing")
    assert policy is not None and policy.kind == Kind.USER_DATA
