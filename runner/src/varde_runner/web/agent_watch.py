"""HTTP watch stream for managed agent sessions."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from typing import Any
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from varde_runner.bot_taint import bot_visible_rows
from varde_runner.clients import ClientRole
from varde_runner.supervisor import Supervisor
from varde_runner.web.agents_route import _agent_rows

KEEPALIVE_SECONDS = 15.0


async def _bot_watch_binding(
    supervisor: Supervisor, actor: str, session_id: str
) -> tuple[str, ClientRole] | None:
    """Server-derived client and role for a bot watcher; None when not visible."""
    visible = bot_visible_rows(actor, await _agent_rows(supervisor))
    if session_id not in {row["session_id"] for row in visible}:
        return None
    return f"bot-watch:{actor}", ClientRole.OBSERVER


def _parse_query(request: Request) -> JSONResponse | tuple[str, ClientRole, int | None]:
    query = request.query_params
    client_id = query.get("client", "")
    after_value = query.get("after")
    try:
        role = ClientRole(query.get("role", ""))
    except ValueError:
        return JSONResponse({"error": "invalid role"}, status_code=400)
    if not client_id or client_id.startswith("system:"):
        return JSONResponse({"error": "invalid client"}, status_code=400)
    try:
        after_seq = int(after_value) if after_value is not None else None
    except ValueError:
        return JSONResponse({"error": "invalid after cursor"}, status_code=400)
    if after_seq is not None and after_seq < 0:
        return JSONResponse({"error": "invalid after cursor"}, status_code=400)
    return client_id, role, after_seq


def create_agent_watch_route(
    get_supervisor: Callable[[], Any], *, keepalive_seconds: float = KEEPALIVE_SECONDS
) -> Route:
    """Create the watch route.

    Every request requires `client` and `role` query parameters.
    """

    async def watch_agent(request: Request) -> JSONResponse | StreamingResponse:
        agent_id = request.path_params["id"]
        parsed = _parse_query(request)
        if isinstance(parsed, JSONResponse):
            return parsed
        client_id, role, after_seq = parsed

        supervisor: Supervisor = await get_supervisor()
        row = supervisor.resolve_session(agent_id)
        if row is None:
            return JSONResponse({"error": "agent not found"}, status_code=404)
        session_id = row["id"]
        identity = request.scope.get("bot_identity")
        if identity is not None:
            binding = await _bot_watch_binding(supervisor, identity.actor, session_id)
            if binding is None:
                return JSONResponse({"error": "agent not found"}, status_code=404)
            client_id, role = binding
        attached_role = supervisor.clients.role(session_id, client_id)
        if attached_role is not None and attached_role != role:
            return JSONResponse({"error": "client role mismatch"}, status_code=400)

        async def stream() -> AsyncIterator[bytes]:
            messages = supervisor.watch(
                session_id, after_seq, client_id=client_id, role=role
            )
            pending: asyncio.Task[dict[str, Any]] | None = None
            try:
                while True:
                    if pending is None:
                        pending = asyncio.ensure_future(anext(messages))
                    done, _ = await asyncio.wait({pending}, timeout=keepalive_seconds)
                    if not done:
                        yield b": keepalive\n\n"
                        continue
                    try:
                        message = pending.result()
                    except StopAsyncIteration:
                        return
                    except ValueError as exc:
                        pending = None
                        payload = json.dumps({"error": str(exc)}, ensure_ascii=False)
                        yield f"event: error\ndata: {payload}\n\n".encode()
                        return
                    pending = None
                    event_type = message.get("type")
                    payload = json.dumps(message, ensure_ascii=False, sort_keys=True)
                    yield f"event: {event_type}\ndata: {payload}\n\n".encode()
            finally:
                if pending is not None:
                    pending.cancel()
                    with suppress(asyncio.CancelledError):
                        await pending
                await messages.aclose()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
        )

    return Route("/api/agents/{id:str}/watch", watch_agent)


def watch_url(
    agent: str,
    *,
    after: int | None,
    client: str,
    role: ClientRole,
    port: int,
) -> str:
    query = f"client={quote(client, safe='')}&role={role.value}"
    if after is not None:
        query += f"&after={after}"
    return f"http://127.0.0.1:{port}/api/agents/{quote(agent, safe='')}/watch?{query}"
