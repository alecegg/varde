"""The gateway wired into the real app, and token plumbing through the Supervisor."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from bot_helpers import call
from fakes.plugin import FakePlugin
from varde_runner.bot_profile import BOT_ROLE, BOT_TOKEN_ENV, PROFILE_RESTRICTED
from varde_runner.bot_tokens import BOT_ACTOR, TOKEN_HEADER, BotTokens
from varde_runner.config import default_config
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSpec
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.supervisor import Supervisor
from varde_runner.web.app import create_app

LOCAL = {"host": "127.0.0.1:8765", "origin": "http://127.0.0.1:8765"}


@pytest.fixture
def app(tmp_path):
    return create_app(data_dir=tmp_path / "data", bound_port=8765)


def bot_headers(app) -> dict[str, str]:
    return {**LOCAL, TOKEN_HEADER: app.state.bot_tokens.issue("bot-session")}


def test_a_bot_token_cannot_reach_a_user_only_route_and_the_denial_is_audited(
    app,
) -> None:
    headers = bot_headers(app)
    status, body = asyncio.run(
        call(app, "POST", "/api/mailbox/d1/dismiss", {}, headers)
    )
    assert status == 403 and "user only" in body["error"]
    row = app.state.bot_audit.repo.audit_page(limit=1)[0]
    assert (row.status, row.action, row.actor) == (
        "denied",
        "POST /api/mailbox/{decision_id:str}/dismiss",
        BOT_ACTOR,
    )


def test_the_same_route_without_a_token_is_not_the_gateways_business(app) -> None:
    _, body = asyncio.run(call(app, "POST", "/api/mailbox/d1/dismiss", {}, LOCAL))
    assert "user only" not in str(body)
    assert app.state.bot_audit.repo.audit_page() == []


def test_the_bot_can_read_its_own_audit_log(app) -> None:
    headers = bot_headers(app)
    asyncio.run(call(app, "POST", "/api/settings", {}, headers))
    status, rows = asyncio.run(call(app, "GET", "/api/bot/audit", None, headers))
    assert status == 200
    assert [row["status"] for row in rows][-1] == "denied"


def test_an_unknown_token_gets_401_from_the_real_app(app) -> None:
    status, _ = asyncio.run(
        call(app, "GET", "/api/queue", None, {**LOCAL, TOKEN_HEADER: "x"})
    )
    assert status == 401


def test_launch_by_the_bot_is_checked_before_the_launch_handler(app) -> None:
    headers = bot_headers(app)
    body = {"role": "builder", "workspace": "w", "prompt": "p"}
    status, payload = asyncio.run(call(app, "POST", "/api/agents", body, headers))
    assert status == 403 and "launch_roles" in payload["error"]


class TokenPlugin(FakePlugin):
    def __init__(self) -> None:
        super().__init__(
            RunnerCapabilities(resume=True, respond=True, restricted_profile=True)
        )
        self.overlays: list[tuple[str, dict[str, str]]] = []

    def set_env_overlay(self, ref, env) -> None:
        self.overlays.append((ref.session_id, dict(env)))


def build(tmp_path, monkeypatch):
    config = replace(default_config(), stall_after_s=10)
    monkeypatch.setattr("varde_runner.supervisor.load_config", lambda *_: config)
    plugin = TokenPlugin()
    registry = PluginRegistry(["claude_cli"])
    registry.register("claude_cli", plugin)
    supervisor = Supervisor(tmp_path, registry)
    tokens = BotTokens()
    supervisor.bot_token_issuer = tokens.overlay
    asyncio.run(supervisor.start())
    return supervisor, plugin, tokens


def test_a_restricted_start_gets_a_token_bound_to_its_session(
    tmp_path, monkeypatch
) -> None:
    supervisor, plugin, tokens = build(tmp_path, monkeypatch)
    spec = SessionSpec(
        "claude_cli", "m", "w", str(tmp_path), "", profile=PROFILE_RESTRICTED
    )
    ref = asyncio.run(supervisor.start_session(spec, BOT_ROLE))
    token = plugin.started[0].env[BOT_TOKEN_ENV]
    identity = tokens.resolve(token)
    assert identity is not None and identity.session_id == ref.session_id
    assert token not in repr(plugin.started[0])


def test_a_normal_start_gets_no_token(tmp_path, monkeypatch) -> None:
    supervisor, plugin, _ = build(tmp_path, monkeypatch)
    spec = SessionSpec("claude_cli", "m", "w", str(tmp_path), "")
    asyncio.run(supervisor.start_session(spec, "builder"))
    assert BOT_TOKEN_ENV not in plugin.started[0].env


def test_resume_reissues_the_token_and_the_old_one_stops_working(
    tmp_path, monkeypatch
) -> None:
    supervisor, plugin, tokens = build(tmp_path, monkeypatch)
    spec = SessionSpec(
        "claude_cli", "m", "w", str(tmp_path), "", profile=PROFILE_RESTRICTED
    )
    ref = asyncio.run(supervisor.start_session(spec, BOT_ROLE))
    first = plugin.started[0].env[BOT_TOKEN_ENV]
    row = supervisor.store.get_session(ref.session_id)
    assert row is not None
    supervisor._reissue_bot_token(row, plugin, SessionRef("claude_cli", "remote-1"))
    assert plugin.overlays[0][0] == "remote-1"
    second = plugin.overlays[0][1][BOT_TOKEN_ENV]
    assert (
        second != first
        and tokens.resolve(first) is None
        and tokens.resolve(second) is not None
    )


def test_other_roles_are_not_reissued(tmp_path, monkeypatch) -> None:
    supervisor, plugin, _ = build(tmp_path, monkeypatch)
    ref = asyncio.run(
        supervisor.start_session(
            SessionSpec("claude_cli", "m", "w", str(tmp_path), ""), "builder"
        )
    )
    row = supervisor.store.get_session(ref.session_id)
    assert row is not None
    supervisor._reissue_bot_token(row, plugin, SessionRef("claude_cli", "remote-1"))
    assert plugin.overlays == []


def test_the_launch_route_records_the_gateway_identity_not_a_client_field(
    monkeypatch,
) -> None:
    from starlette.applications import Starlette
    from varde_runner.bot_tokens import BotIdentity
    from varde_runner.web.agents_route import create_agents_routes

    seen: dict = {}

    async def fake_launch(*args, **kwargs):
        seen.update(kwargs)
        return SessionRef("p", "agent-1")

    monkeypatch.setattr("varde_runner.web.agents_route.launch_agent", fake_launch)
    inner = Starlette(routes=create_agents_routes(object))

    async def with_identity(scope, receive, send):
        scope["bot_identity"] = BotIdentity(BOT_ACTOR, "s1")
        await inner(scope, receive, send)

    body = {
        "workspace": "w",
        "role": "planner",
        "prompt": "p",
        "launched_by": "someone-else",
    }
    status, _ = asyncio.run(call(with_identity, "POST", "/api/agents", body))
    assert status == 201 and seen["launched_by"] == BOT_ACTOR
    seen.clear()
    status, _ = asyncio.run(call(inner, "POST", "/api/agents", body))
    assert status == 201 and seen["launched_by"] is None
