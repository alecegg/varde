from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from bot_helpers import call
from varde_runner.bot_actions import PROVENANCE_LINE, replace_plan_body, with_provenance
from varde_runner.bot_tokens import BOT_ACTOR, TOKEN_HEADER
from varde_runner.varde_cli import VardeCLI
from varde_runner.web.app import create_app

LOCAL = {"host": "127.0.0.1:8765", "origin": "http://127.0.0.1:8765"}


def _headers(app):
    return {**LOCAL, TOKEN_HEADER: app.state.bot_tokens.issue("bot-session")}


def _app(data_dir: Path):
    cli = VardeCLI(cwd=data_dir, env={"VARDE_WORKING_DIR": str(data_dir)})
    return create_app(data_dir=data_dir, cli=cli, bound_port=8765)


def test_provenance_is_added_once_and_plan_frontmatter_is_byte_preserved():
    assert with_provenance("do the work") == f"{PROVENANCE_LINE}\ndo the work"
    assert with_provenance(f"{PROVENANCE_LINE}\ndo the work") == (
        f"{PROVENANCE_LINE}\ndo the work"
    )
    original = b"---\r\ntype: plan\r\nstatus: backlog\r\n---\r\nold\r\n"
    updated = replace_plan_body(original, "new\n")
    assert updated == b"---\r\ntype: plan\r\nstatus: backlog\r\n---\r\nnew\n"
    assert replace_plan_body(b"no frontmatter", "new") is None


def test_bot_say_notes_and_mailbox_are_gateway_actions(tmp_path: Path):
    data_dir = tmp_path / "data"
    app = _app(data_dir)
    messages: list[dict] = []
    app.state.cli.send = lambda **message: messages.append(message) or {"id": "mail-1"}
    headers = _headers(app)

    status, say = asyncio.run(
        call(app, "POST", "/api/bot/say", {"text": "I finished the task."}, headers)
    )
    assert status == 201 and say["message_id"]
    event = app.state.bot_audit.chat.page("main")[-1]
    assert (event.kind, event.text) == ("say", "I finished the task.")

    status, _ = asyncio.run(
        call(app, "POST", "/api/bot/notes", {"text": "Keep this decision."}, headers)
    )
    assert status == 200
    notes = tmp_path / "data/session-notes/manager-bot/notes.md"
    assert notes.read_text(encoding="utf-8") == "Keep this decision.\n"

    status, mailbox = asyncio.run(
        call(
            app,
            "POST",
            "/api/bot/mailbox",
            {"asked": "Continue?", "why": "Need a choice.", "options": ["Yes", "No"]},
            headers,
        )
    )
    assert status == 201 and mailbox["message_id"]
    assert messages == [
        {
            "sender": "manager",
            "recipient": "main",
            "kind": "needs-user",
            "text": "Manager bot asks: Continue?",
            "notes": messages[0]["notes"],
        }
    ]
    assert Path(messages[0]["notes"]).exists()
    message = messages[0]
    assert (message["sender"], message["recipient"], message["kind"]) == (
        "manager",
        "main",
        "needs-user",
    )

    rows = app.state.bot_audit.repo.audit_page(limit=10)
    assert all(row.actor == BOT_ACTOR for row in rows)


def test_bot_action_routes_refuse_calls_without_a_bot_identity(tmp_path: Path):
    app = _app(tmp_path / "data")
    status, body = asyncio.run(
        call(app, "POST", "/api/bot/say", {"text": "bypass"}, LOCAL)
    )
    assert status == 403 and "bot identity" in body["error"]
    assert not app.state.bot_audit.chat.page("main")


def test_backlog_body_edit_validates_and_keeps_frontmatter_unchanged(
    tmp_path: Path, monkeypatch
):
    data_dir = tmp_path / "data"
    plan = data_dir / "plans" / "plan-1" / "plan.md"
    plan.parent.mkdir(parents=True)
    frontmatter = b"---\ntype: plan\nstatus: backlog\ntitle: Existing\n---\n"
    plan.write_bytes(frontmatter + b"Old body\n")
    app = _app(data_dir)
    validated: list[Path] = []

    def validate(*args):
        assert args[:2] == ("plan", "validate")
        candidate = Path(args[2])
        validated.append(candidate)
        assert candidate.read_bytes().startswith(frontmatter)
        return {"valid": True}

    monkeypatch.setattr(app.state.cli, "_json", validate)
    status, result = asyncio.run(
        call(
            app,
            "PUT",
            "/api/plans/plan-1/body",
            {"body": "Updated body\n"},
            _headers(app),
        )
    )
    assert status == 200 and result["saved"] is True
    assert plan.read_bytes() == frontmatter + b"Updated body\n"
    assert len(validated) == 1 and not validated[0].exists()


def test_plan_body_route_rejects_frontmatter_fields(tmp_path: Path):
    app = _app(tmp_path / "data")
    status, body = asyncio.run(
        call(
            app,
            "PUT",
            "/api/plans/plan-1/body",
            {"body": "new", "status": "active"},
            _headers(app),
        )
    )
    assert status == 403 and "fields not allowed" in body["error"]


def test_bot_plan_comment_is_stored_as_manager_with_provenance(tmp_path: Path):
    data_dir = tmp_path / "data"
    plan = data_dir / "plans" / "plan-1" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntype: plan\nstatus: backlog\ntitle: Existing\n---\n## Body\n",
        encoding="utf-8",
    )
    app = _app(data_dir)
    status, result = asyncio.run(
        call(
            app,
            "POST",
            "/api/plans/plan-1/comments",
            {"target": "plan", "text": "Review this."},
            _headers(app),
        )
    )
    assert status == 201
    assert result["comment"]["sender"] == "manager"
    assert result["comment"]["text"] == f"{PROVENANCE_LINE}\nReview this."

    deliveries: list[dict] = []
    app.state.cli.read_address_bindings = lambda: [{"address": "plan-1"}]
    app.state.cli.send = lambda **message: deliveries.append(message) or {"id": "m1"}
    status, _ = asyncio.run(
        call(
            app,
            "POST",
            "/api/plans/plan-1/comments",
            {"target": "plan", "text": "Send this to the orchestrator."},
            _headers(app),
        )
    )
    assert status == 201
    assert deliveries[0]["sender"] == "manager"


def test_gateway_prepends_provenance_to_launch_prompt_and_agent_prompt(tmp_path: Path):
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_runner.bot_audit import BotAudit
    from varde_runner.bot_constraints import BotConfig, ConstraintContext
    from varde_runner.bot_gateway import BotGateway
    from varde_runner.bot_tokens import BotTokens

    received: list[dict] = []

    async def capture(request: Request) -> JSONResponse:
        received.append(await request.json())
        return JSONResponse({"agent_id": "launched"}, status_code=201)

    async def prompt(request: Request) -> JSONResponse:
        received.append(await request.json())
        return JSONResponse({"outcome": "sent"})

    routes = [
        Route("/api/agents", capture, methods=["POST"]),
        Route("/api/agents/{id:str}/prompt", prompt, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    data = open_data(tmp_path, load_data_config())
    audit = BotAudit(data.bot, data.chat)
    tokens = BotTokens()
    token = tokens.issue("bot-session")

    async def context():
        return ConstraintContext(
            workspace_listed=lambda _: True,
            slot_bound=lambda _: False,
            plan_bound=lambda _: False,
            launched_by=lambda _: BOT_ACTOR,
            plan_exists=lambda _: True,
        )

    wrapped = BotGateway(
        app,
        routes=lambda: app.routes,
        tokens=tokens,
        audit=audit,
        config=BotConfig,
        context=context,
    )
    launch_body = {"role": "orchestrator", "workspace": "ws", "prompt": "launch"}
    prompt_body = {"client": "manager", "text": "continue"}
    status, _ = asyncio.run(
        call(
            wrapped, "POST", "/api/agents", launch_body, {**LOCAL, TOKEN_HEADER: token}
        )
    )
    assert status == 201
    status, _ = asyncio.run(
        call(
            wrapped,
            "POST",
            "/api/agents/a1/prompt",
            prompt_body,
            {**LOCAL, TOKEN_HEADER: token},
        )
    )
    assert status == 200
    assert received == [
        {**launch_body, "prompt": f"{PROVENANCE_LINE}\nlaunch"},
        {**prompt_body, "text": f"{PROVENANCE_LINE}\ncontinue"},
    ]


def test_launch_fallback_records_one_event_when_identity_differs(monkeypatch):
    from starlette.applications import Starlette
    from varde_runner.bot_tokens import BotIdentity
    from varde_runner.web.agents_route import create_agents_routes

    events: list[tuple[str, str, str, str]] = []

    def record_fallback(agent_id: str) -> None:
        events.append(
            ("event", "no match, used closest role", f"/agents/{agent_id}", "main")
        )

    async def launch(*_args, **_kwargs):
        return SimpleNamespace(session_id="agent-1")

    monkeypatch.setattr("varde_runner.web.agents_route.launch_agent", launch)
    app = Starlette(
        routes=[*create_agents_routes(object, on_identity_fallback=record_fallback)]
    )

    async def as_bot(scope, receive, send):
        scope["bot_identity"] = BotIdentity(BOT_ACTOR, "manager-1")
        await app(scope, receive, send)

    status, _ = asyncio.run(
        call(
            as_bot,
            "POST",
            "/api/agents",
            {
                "role": "orchestrator",
                "workspace": "workspace-1",
                "prompt": "Do the task.",
                "requested_identity": "builder",
            },
        )
    )
    assert status == 201
    assert events == [
        ("event", "no match, used closest role", "/agents/agent-1", "main")
    ]
    status, _ = asyncio.run(
        call(
            as_bot,
            "POST",
            "/api/agents",
            {
                "role": "orchestrator",
                "workspace": "workspace-1",
                "prompt": "Do the task.",
                "requested_identity": "orchestrator",
            },
        )
    )
    assert status == 201
    assert len(events) == 1
