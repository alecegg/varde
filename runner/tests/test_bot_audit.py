from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from bot_helpers import call
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from varde_data.bot import open_bot
from varde_data.repos.chat import ChatRepository
from varde_runner.bot_actions import PROVENANCE_LINE
from varde_runner.bot_audit import BotAudit, digest_args, redact_args
from varde_runner.bot_constraints import BotConfig, ConstraintContext
from varde_runner.bot_gateway import BotGateway, Refusal
from varde_runner.bot_tokens import BOT_ACTOR, TOKEN_HEADER, BotTokens
from varde_runner.web.bot_audit_route import create_bot_audit_routes


@dataclass
class FakeChat:
    events: list[tuple[str, str, str | None]] = field(default_factory=list)
    fail: bool = False

    def append_event(self, kind, summary, link, thread_key="main"):
        if self.fail:
            raise RuntimeError("chat down")
        self.events.append((kind, summary, link))
        return type("Msg", (), {"id": f"m{len(self.events)}"})()


class Harness:
    """A small app on the real route templates, behind a real gateway."""

    def __init__(
        self, tmp_path, *, run_state="running", governor=None, after=None, release=None
    ) -> None:
        self.repo = open_bot(tmp_path)
        self.chat = FakeChat()
        self.audit = BotAudit(self.repo, cast("ChatRepository", self.chat))
        self.tokens = BotTokens()
        self.token = self.tokens.issue("bot-session")
        self.state: dict[str, Any] = {"run": run_state}
        self.calls: list[tuple[str, dict, Any]] = []
        self.owner = {"mine": BOT_ACTOR}

        async def handler(request):
            body = await request.body()
            self.calls.append(
                (
                    request.url.path,
                    json.loads(body) if body else {},
                    request.scope.get("bot_identity"),
                )
            )
            if request.url.path == "/api/agents" and self.state.get("launch_pauses"):
                self.state["run"] = "paused"
            return JSONResponse(
                {"agent_id": "new-agent"},
                status_code=201 if request.method == "POST" else 200,
            )

        async def boom(request):
            raise RuntimeError("handler exploded")

        routes = [
            Route("/api/agents", handler, methods=["GET", "POST"]),
            Route("/api/agents/{id:str}/stop", handler, methods=["POST"]),
            Route("/api/agents/{id:str}/respond", handler, methods=["POST"]),
            Route("/api/queue", handler),
            Route("/api/mailbox/{decision_id:str}/answer", handler, methods=["POST"]),
            Route("/api/queue/move", boom, methods=["POST"]),
            Route("/api/not-in-the-table", handler, methods=["POST"]),
            *create_bot_audit_routes(self.audit),
        ]
        inner = Starlette(routes=routes)

        async def context() -> ConstraintContext:
            return ConstraintContext(
                workspace_listed=lambda workspace: workspace == "ws-1",
                slot_bound=lambda slot: False,
                plan_bound=lambda plan: False,
                launched_by=self.owner.get,
                plan_exists=lambda plan: True,
            )

        self.app = BotGateway(
            inner,
            routes=lambda: inner.routes,
            tokens=self.tokens,
            audit=self.audit,
            config=BotConfig,
            context=context,
            run_state=lambda: self.state["run"],
            governor=governor,
            after=after,
            release=release,
        )

    def headers(self) -> dict[str, str]:
        return {TOKEN_HEADER: self.token}

    def send(self, method, path, payload=None, **kwargs):
        return asyncio.run(
            call(self.app, method, path, payload, self.headers(), **kwargs)
        )

    def rows(self):
        return list(reversed(self.repo.audit_page(limit=200)))


LAUNCH = {"role": "orchestrator", "workspace": "ws-1", "prompt": "do the secret thing"}


def test_requests_without_a_token_pass_through_unaudited(tmp_path) -> None:
    h = Harness(tmp_path)
    status, _ = asyncio.run(call(h.app, "POST", "/api/agents/mine/stop", {}))
    assert status == 201 and len(h.calls) == 1
    assert h.rows() == []


def test_an_unknown_token_is_refused_before_any_handler(tmp_path) -> None:
    h = Harness(tmp_path)
    status, body = asyncio.run(
        call(h.app, "GET", "/api/queue", None, {TOKEN_HEADER: "nope"})
    )
    assert (status, body) == (401, {"error": "invalid bot token"})
    assert h.calls == []


def test_a_read_writes_a_call_and_a_result_row_but_no_event(tmp_path) -> None:
    h = Harness(tmp_path)
    status, _ = h.send("GET", "/api/queue")
    assert status == 200
    call_row, result_row = h.rows()
    assert (call_row.phase, call_row.status, call_row.actor) == (
        "call",
        "read",
        BOT_ACTOR,
    )
    assert (result_row.phase, result_row.status, result_row.reason) == (
        "result",
        "ok",
        "http 200",
    )
    assert h.chat.events == []


def test_an_allowed_launch_replays_the_body_and_sets_the_identity(tmp_path) -> None:
    h = Harness(tmp_path)
    status, body = h.send("POST", "/api/agents", LAUNCH)
    assert (status, body) == (201, {"agent_id": "new-agent"})
    _, received, identity = h.calls[0]
    assert received == {**LAUNCH, "prompt": f"{PROVENANCE_LINE}\n{LAUNCH['prompt']}"}
    assert identity.actor == BOT_ACTOR and identity.session_id == "bot-session"
    call_row, result_row = h.rows()
    assert (call_row.status, call_row.action, result_row.status) == (
        "allowed",
        "launch",
        "ok",
    )
    assert (
        "secret" not in call_row.redacted_args
        and "[19 chars]" in call_row.redacted_args
    )
    assert call_row.args_digest == digest_args(LAUNCH)
    assert (call_row.agent_id, result_row.agent_id) == (None, "new-agent")
    assert [event[1] for event in h.chat.events] == ["Bot: launch"]


def test_every_user_only_route_is_refused_with_an_audited_denied_row(tmp_path) -> None:
    h = Harness(tmp_path)
    for path in ("/api/mailbox/d1/answer", "/api/agents/mine/respond"):
        status, body = h.send("POST", path, {"decision": "approve"})
        assert status == 403 and "user only" in body["error"]
    assert h.calls == []
    assert [(row.phase, row.status) for row in h.rows()] == [("call", "denied")] * 2
    assert [event[1].split(":")[0] for event in h.chat.events] == ["Refused", "Refused"]


def test_unclassified_and_unmatched_routes_are_denied(tmp_path) -> None:
    h = Harness(tmp_path)
    for method, path in (
        ("POST", "/api/not-in-the-table"),
        ("GET", "/nowhere"),
        ("DELETE", "/api/queue"),
    ):
        status, body = h.send(method, path)
        assert status == 403 and "not classified" in body["error"]
    assert h.calls == []
    assert {row.status for row in h.rows()} == {"denied"}


def test_constraint_refusals_are_audited_and_the_handler_never_runs(tmp_path) -> None:
    h = Harness(tmp_path)
    status, body = h.send("POST", "/api/agents", {**LAUNCH, "role": "builder"})
    assert status == 403 and "launch_roles" in body["error"]
    status, _ = h.send("POST", "/api/agents/other/stop", {})
    assert status == 403
    assert h.calls == []
    assert [row.status for row in h.rows()] == ["denied", "denied"]


def test_the_bot_may_stop_its_own_agent_only(tmp_path) -> None:
    h = Harness(tmp_path)
    assert h.send("POST", "/api/agents/mine/stop", {})[0] == 201
    assert h.rows()[0].agent_id == "mine"


@pytest.mark.parametrize("state", ["paused", "killed"])
def test_paused_or_killed_blocks_writes_with_423_but_not_reads(tmp_path, state) -> None:
    h = Harness(tmp_path, run_state=state)
    status, body = h.send("POST", "/api/agents", LAUNCH)
    assert (status, body["error"]) == (423, f"bot is {state}")
    assert h.send("GET", "/api/queue")[0] == 200
    assert [row.status for row in h.rows()[:1]] == ["denied"]
    assert len(h.calls) == 1


def test_invalid_bodies_are_refused_and_audited(tmp_path) -> None:
    h = Harness(tmp_path)
    assert h.send("POST", "/api/agents", [1, 2])[0] == 400
    assert h.rows()[-1].status == "denied"


def test_fail_closed_a_failed_call_write_gives_503_and_no_handler(
    tmp_path, monkeypatch
) -> None:
    h = Harness(tmp_path)

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(h.repo, "append_audit", broken)
    status, body = h.send("POST", "/api/agents", LAUNCH)
    assert (status, body["error"]) == (503, "audit unavailable")
    assert h.calls == []


def test_a_failed_result_write_does_not_lose_the_response(
    tmp_path, monkeypatch
) -> None:
    h = Harness(tmp_path)
    original = h.repo.append_audit

    def fail_result(phase, *args, **kwargs):
        if phase == "result":
            raise OSError("disk full")
        return original(phase, *args, **kwargs)

    monkeypatch.setattr(h.repo, "append_audit", fail_result)
    assert h.send("POST", "/api/agents", LAUNCH)[0] == 201


def test_a_handler_exception_is_recorded_as_an_error_result(tmp_path) -> None:
    h = Harness(tmp_path)
    with pytest.raises(RuntimeError, match="exploded"):
        h.send("POST", "/api/queue/move", {"plan": "p", "direction": "up"})
    assert h.rows()[-1].phase == "result" and h.rows()[-1].status == "error"


def test_failed_event_rows_are_retried_from_the_audit_log(tmp_path) -> None:
    h = Harness(tmp_path)
    h.chat.fail = True
    h.send("POST", "/api/mailbox/d1/answer", {})
    assert h.chat.events == [] and len(h.repo.unevented_audit()) == 1
    h.chat.fail = False
    assert h.audit.retry_events() == 1
    assert h.audit.retry_events() == 0
    assert len(h.chat.events) == 1 and h.repo.unevented_audit() == []


def test_the_governor_can_refuse_writes_and_is_not_asked_about_reads(tmp_path) -> None:
    asked: list[str] = []

    async def governor(identity, classified, body):
        asked.append(classified.route_key)
        return Refusal(429, "max_launches_per_hour")

    h = Harness(tmp_path, governor=governor)
    assert h.send("GET", "/api/queue")[0] == 200
    status, body = h.send("POST", "/api/agents", LAUNCH)
    assert (status, body["error"]) == (429, "max_launches_per_hour")
    assert asked == ["POST /api/agents"] and len(h.calls) == 1
    assert h.rows()[-1].status == "denied"


def test_a_launch_that_raced_pause_triggers_the_after_hook(tmp_path) -> None:
    seen: list[tuple[int, bytes]] = []

    async def after(identity, classified, status, body):
        seen.append((status, body))

    h = Harness(tmp_path, after=after)
    h.send("POST", "/api/agents", LAUNCH)
    assert seen == []
    h.state["launch_pauses"] = True
    assert h.send("POST", "/api/agents", LAUNCH)[0] == 201
    assert (
        seen
        and seen[0][0] == 201
        and json.loads(seen[0][1]) == {"agent_id": "new-agent"}
    )


def test_the_audit_route_pages_newest_first_and_there_is_no_mutation_route(
    tmp_path,
) -> None:
    h = Harness(tmp_path)
    for _ in range(3):
        h.send("GET", "/api/queue")
    status, rows = h.send("GET", "/api/bot/audit", query="limit=2")
    assert status == 200 and len(rows) == 2 and rows[0]["id"] > rows[1]["id"]
    older = h.send("GET", "/api/bot/audit", query=f"before={rows[-1]['id']}&limit=50")[
        1
    ]
    assert all(row["id"] < rows[-1]["id"] for row in older)
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        assert h.send(method, "/api/bot/audit", {})[0] in {403, 405}
    assert not [n for n in dir(h.audit) if n.startswith(("update", "delete", "remove"))]


def test_redaction_keeps_structure_and_truncates() -> None:
    assert (
        redact_args({"role": "planner", "prompt": "abc", "n": 1})
        == '{"n":1,"prompt":"[3 chars]","role":"planner"}'
    )
    assert len(redact_args({"x": "y" * 2000})) < 600


def test_tokens_resolve_to_identity_rotate_and_revoke() -> None:
    tokens = BotTokens()
    first = tokens.issue("s1")
    assert tokens.resolve(first).actor == BOT_ACTOR  # type: ignore[union-attr]
    second = tokens.issue("s1")
    assert tokens.resolve(first) is None and tokens.resolve(second) is not None
    assert tokens.overlay("s1")["VARDE_BOT_TOKEN"] != second
    tokens.revoke_session("s1")
    assert tokens.resolve(second) is None
    assert tokens.resolve("") is None


def test_the_release_hook_runs_after_the_handler_and_after_a_failed_call_write(
    tmp_path, monkeypatch
) -> None:
    released: list[str] = []
    h = Harness(tmp_path, release=lambda classified: released.append("r"))
    h.send("POST", "/api/agents", LAUNCH)
    assert released == ["r"]

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(h.repo, "append_audit", broken)
    h.send("POST", "/api/agents", LAUNCH)
    assert released == ["r", "r"]


def test_a_failed_event_write_is_retried_on_the_loop_until_it_is_linked(
    tmp_path,
) -> None:
    h = Harness(tmp_path)
    h.audit.retry_seconds = 0.01

    async def run() -> None:
        h.chat.fail = True
        status, _ = await call(h.app, "POST", "/api/mailbox/d1/answer", {}, h.headers())
        assert status == 403
        assert h.chat.events == []
        await asyncio.sleep(0.05)  # still failing: the retry keeps rescheduling
        assert h.chat.events == [] and len(h.repo.unevented_audit()) == 1
        h.chat.fail = False
        for _ in range(100):
            if h.chat.events:
                break
            await asyncio.sleep(0.01)
        assert len(h.chat.events) == 1 and h.repo.unevented_audit() == []

    asyncio.run(run())


def test_unposted_events_are_posted_at_startup_after_a_restart(tmp_path) -> None:
    h = Harness(tmp_path)
    h.chat.fail = True
    h.send("POST", "/api/mailbox/d1/answer", {})
    assert len(h.repo.unevented_audit()) == 1
    h.chat.fail = False
    restarted = BotAudit(h.repo, cast("ChatRepository", h.chat))
    restarted.start_retries()
    assert len(h.chat.events) == 1 and h.repo.unevented_audit() == []


def test_allowed_permission_rows_never_need_an_event(tmp_path) -> None:
    h = Harness(tmp_path)
    h.audit.record(
        "call",
        action="permission",
        route="permission Bash",
        args={},
        actor=BOT_ACTOR,
        status="allowed",
    )
    assert h.repo.unevented_audit() == []
    h.audit.record(
        "call",
        action="permission",
        route="permission Bash",
        args={},
        actor=BOT_ACTOR,
        status="denied",
    )
    assert len(h.repo.unevented_audit()) == 1
