"""The single choke point for bot-rooted requests (pure ASGI, fail closed).

Order: identify -> route policy -> pause state -> constraints -> governor hook ->
`call` audit row -> handler -> `result` audit row -> race re-check. A request
without a bot token passes through untouched; a request with an unknown token is
refused. Nothing here updates or deletes an audit row.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from starlette.responses import JSONResponse
from starlette.routing import BaseRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from varde_runner.bot_actions import with_provenance
from varde_runner.bot_audit import BotAudit
from varde_runner.bot_constraints import BotConfig, ConstraintContext, check
from varde_runner.bot_route_policy import Classified, Kind, classify
from varde_runner.bot_tokens import TOKEN_HEADER, BotIdentity, BotTokens

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 1 << 20
MAX_CAPTURED_RESPONSE_BYTES = 64 * 1024
RUN_STATE_RUNNING = "running"
IDENTITY_SCOPE_KEY = "bot_identity"


@dataclass(frozen=True, slots=True)
class Refusal:
    status: int
    reason: str


Governor = Callable[
    [BotIdentity, Classified, Mapping[str, Any]], Awaitable[Refusal | None]
]
AfterHook = Callable[[BotIdentity, Classified, int, bytes], Awaitable[None]]


def _header(scope: Scope, name: str) -> str | None:
    for key, value in scope.get("headers", ()):
        if key.decode("latin-1").lower() == name:
            return value.decode("latin-1")
    return None


def _action_name(classified: Classified) -> str:
    policy = classified.policy
    if policy is not None and policy.constraint is not None:
        last = classified.route_key.rsplit("/", 1)[-1]
        return (
            f"agent_{last}"
            if policy.constraint == "agent_action"
            else policy.constraint
        )
    return classified.route_key


def _provenance_body(classified: Classified, body: dict[str, Any]) -> dict[str, Any]:
    route = classified.route_key
    if classified.policy is None:
        return body
    field = None
    if classified.policy.constraint == "launch":
        field = "prompt"
    elif route.endswith("/prompt") or classified.policy.constraint == "plan_comment":
        field = "text"
    if field is None or not isinstance(body.get(field), str):
        return body
    return {**body, field: with_provenance(body[field])}


class BotGateway:
    def __init__(  # noqa: PLR0913 - the gateway's collaborators, all keyword-only
        self,
        app: ASGIApp,
        *,
        routes: Callable[[], Sequence[BaseRoute]],
        tokens: BotTokens,
        audit: BotAudit,
        config: Callable[[], BotConfig],
        context: Callable[[], Awaitable[ConstraintContext]],
        run_state: Callable[[], str] = lambda: RUN_STATE_RUNNING,
        governor: Governor | None = None,
        after: AfterHook | None = None,
        release: Callable[[Classified], None] | None = None,
    ) -> None:
        self.app = app
        self.routes = routes
        self.tokens = tokens
        self.audit = audit
        self.config = config
        self.context = context
        self.run_state = run_state
        self.governor = governor
        self.after = after
        self.release = release

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        token = _header(scope, TOKEN_HEADER) if scope["type"] == "http" else None
        if token is None:
            await self.app(scope, receive, send)
            return
        identity = self.tokens.resolve(token)
        if identity is None:
            await self._reply(scope, receive, send, Refusal(401, "invalid bot token"))
            return
        await self._gateway(identity, scope, receive, send)

    async def _gateway(
        self, identity: BotIdentity, scope: Scope, receive: Receive, send: Send
    ) -> None:
        classified = classify(self.routes(), scope)
        kind = classified.policy.kind if classified.policy else None
        body: dict[str, Any] = {}
        raw = b""
        if kind == Kind.ALLOW:
            raw, parsed = await self._read_body(receive)
            if isinstance(parsed, Refusal):
                await self._deny(identity, classified, {}, parsed, scope, receive, send)
                return
            body = parsed
        refusal = await self._decide(identity, classified, body)
        if refusal is not None:
            await self._deny(identity, classified, body, refusal, scope, receive, send)
            return
        params = self._args(classified, body, scope)
        routed_body = _provenance_body(classified, body) if kind == Kind.ALLOW else body
        if routed_body != body:
            raw = json.dumps(
                routed_body, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        try:
            call_row = self.audit.record(
                "call",
                action=_action_name(classified),
                route=classified.route_key,
                args=params,
                actor=identity.actor,
                status="read" if kind == Kind.READ else "allowed",
                agent_id=self._agent_id(classified),
                plan_id=self._plan_id(classified, body),
            )
        except Exception:
            logger.exception("bot audit write failed; refusing the request")
            self._release(classified)
            await self._reply(scope, receive, send, Refusal(503, "audit unavailable"))
            return
        if kind != Kind.READ:
            self.audit.post_event(call_row)
        try:
            await self._run_handler(
                identity, classified, kind, raw, params, scope, receive, send
            )
        finally:
            self._release(classified)

    def _release(self, classified: Classified) -> None:
        if self.release is not None:
            self.release(classified)

    async def _decide(
        self, identity: BotIdentity, classified: Classified, body: Mapping[str, Any]
    ) -> Refusal | None:
        policy = classified.policy
        if policy is None:
            return Refusal(403, "route is not classified for the bot")
        if policy.kind in (Kind.USER_ONLY, Kind.USER_DATA):
            return Refusal(403, "this route is for the user only")
        if policy.kind != Kind.READ and self.run_state() != RUN_STATE_RUNNING:
            return Refusal(423, f"bot is {self.run_state()}")
        if policy.kind == Kind.ALLOW:
            params = dict(classified.params)
            params["action"] = classified.route_key.rsplit("/", 1)[-1]
            reason = check(
                policy.constraint or "",
                params,
                body,
                self.config(),
                await self.context(),
                identity,
            )
            if reason is not None:
                return Refusal(403, reason)
        if self.governor is not None and policy.kind != Kind.READ:
            return await self.governor(identity, classified, body)
        return None

    async def _deny(  # noqa: PLR0913, PLR0917 - one refusal path
        self,
        identity: BotIdentity,
        classified: Classified,
        body: Mapping[str, Any],
        refusal: Refusal,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        try:
            row = self.audit.record(
                "call",
                action=_action_name(classified),
                route=classified.route_key,
                args=self._args(classified, body, scope),
                actor=identity.actor,
                status="denied",
                reason=refusal.reason,
                agent_id=self._agent_id(classified),
                plan_id=self._plan_id(classified, body),
            )
            self.audit.post_event(row)
        except Exception:
            logger.exception("could not audit a denied bot request")
        await self._reply(scope, receive, send, refusal)

    async def _run_handler(  # noqa: PLR0913, PLR0917 - one handler call
        self,
        identity: BotIdentity,
        classified: Classified,
        kind: Kind | None,
        raw: bytes,
        params: Mapping[str, Any],
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        captured = {"status": 0, "body": bytearray()}
        want_body = kind != Kind.READ

        async def capture(message: Message) -> None:
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
            elif want_body and len(captured["body"]) < MAX_CAPTURED_RESPONSE_BYTES:
                captured["body"] += message.get("body", b"")
            await send(message)

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if kind == Kind.ALLOW and not replayed:
                replayed = True
                return {"type": "http.request", "body": raw, "more_body": False}
            return await receive()

        inner = {**scope, IDENTITY_SCOPE_KEY: identity}
        try:
            await self.app(inner, replay if kind == Kind.ALLOW else receive, capture)
        except Exception as exc:
            self._record_result(
                identity, classified, params, "error", f"{type(exc).__name__}"
            )
            raise
        status = captured["status"]
        self._record_result(
            identity,
            classified,
            params,
            "ok" if 200 <= status < 400 else "error",
            f"http {status}",
            self._created_agent(classified, bytes(captured["body"])),
        )
        await self._after(identity, classified, kind, status, bytes(captured["body"]))

    async def _after(
        self,
        identity: BotIdentity,
        classified: Classified,
        kind: Kind | None,
        status: int,
        body: bytes,
    ) -> None:
        raced = (
            kind == Kind.ALLOW
            and 200 <= status < 300
            and self.run_state() != RUN_STATE_RUNNING
        )
        if self.after is None or not raced:
            return
        try:
            await self.after(identity, classified, status, body)
        except Exception:
            logger.exception("bot race hook failed")

    def _record_result(
        self,
        identity: BotIdentity,
        classified: Classified,
        params: Mapping[str, Any],
        status: str,
        reason: str,
        created_agent: str | None = None,
    ) -> None:
        try:
            self.audit.record(
                "result",
                action=_action_name(classified),
                route=classified.route_key,
                args=params,
                actor=identity.actor,
                status=status,
                reason=reason,
                agent_id=self._agent_id(classified) or created_agent,
            )
        except Exception:
            logger.exception("could not write the bot result row")

    @staticmethod
    def _created_agent(classified: Classified, body: bytes) -> str | None:
        """The agent id a launch response created (loop detection pairs stops to it)."""
        policy = classified.policy
        if policy is None or policy.constraint != "launch":
            return None
        try:
            value = json.loads(body).get("agent_id")
        except ValueError, AttributeError:
            return None
        return value if isinstance(value, str) else None

    @staticmethod
    def _args(
        classified: Classified, body: Mapping[str, Any], scope: Scope
    ) -> dict[str, Any]:
        args: dict[str, Any] = {**body}
        if classified.params:
            args["path"] = dict(classified.params)
        query = scope.get("query_string", b"")
        if query:
            args["query"] = query.decode("latin-1")[:200]
        return args

    @staticmethod
    def _agent_id(classified: Classified) -> str | None:
        value = classified.params.get("id") or classified.params.get("agent_id")
        return str(value) if value else None

    @staticmethod
    def _plan_id(classified: Classified, body: Mapping[str, Any]) -> str | None:
        value = classified.params.get("plan_id") or body.get("plan")
        return value if isinstance(value, str) else None

    @staticmethod
    async def _read_body(receive: Receive) -> tuple[bytes, dict[str, Any] | Refusal]:
        chunks = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return b"", Refusal(400, "request was cancelled")
            chunks += message.get("body", b"")
            if len(chunks) > MAX_BODY_BYTES:
                return b"", Refusal(413, "request body is too large")
            if not message.get("more_body"):
                break
        if not chunks:
            return b"", {}
        try:
            parsed = json.loads(bytes(chunks))
        except ValueError:
            return b"", Refusal(400, "body must be JSON")
        if not isinstance(parsed, dict):
            return b"", Refusal(400, "body must be a JSON object")
        return bytes(chunks), parsed

    @staticmethod
    async def _reply(
        scope: Scope, receive: Receive, send: Send, refusal: Refusal
    ) -> None:
        response = JSONResponse({"error": refusal.reason}, status_code=refusal.status)
        await response(scope, receive, send)
