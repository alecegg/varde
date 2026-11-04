"""User-only HTTP routes for instance takeover leases."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from varde_data.errors import NotFound

from varde_runner.takeover import Takeover


def create_takeover_routes(
    takeover: Takeover, get_supervisor: Callable[[], Any]
) -> list[Route]:
    async def post(request: Request) -> JSONResponse:
        payload = await _payload(request)
        if isinstance(payload, JSONResponse):
            return payload
        client = _client(payload)
        if client is None:
            return JSONResponse({"error": "client is required"}, status_code=400)
        supervisor = await _get_supervisor(get_supervisor)
        agent_id = request.path_params["agent_id"]
        session = supervisor.resolve_session(agent_id)
        if session is None:
            return JSONResponse({"error": "agent not found"}, status_code=404)
        if session.get("lifecycle") in {"completed", "archived", "error"}:
            return JSONResponse({"error": "agent is not live"}, status_code=409)
        try:
            acquired = takeover.acquire(agent_id, client)
            current = takeover.repository.get_takeover(f"instance:{agent_id}")
        except NotFound:
            return JSONResponse({"error": "instance thread not found"}, status_code=404)
        if not acquired:
            return JSONResponse({"error": "takeover already held"}, status_code=409)
        queued = takeover.repository.queued_count(f"instance:{agent_id}")
        return JSONResponse(
            {"holder": current.holder_client if current else client, "queued": queued}
        )

    async def delete(request: Request) -> JSONResponse:
        return await _update(request, heartbeat=False)

    async def pulse(request: Request) -> JSONResponse:
        return await _update(request, heartbeat=True)

    async def _update(request: Request, *, heartbeat: bool) -> JSONResponse:
        payload = await _payload(request)
        if isinstance(payload, JSONResponse):
            return payload
        client = _client(payload)
        if client is None:
            return JSONResponse({"error": "client is required"}, status_code=400)
        supervisor = await _get_supervisor(get_supervisor)
        agent_id = request.path_params["agent_id"]
        try:
            changed = (
                takeover.heartbeat(agent_id, client)
                if heartbeat
                else takeover.release(agent_id, client, supervisor)
            )
        except NotFound:
            return JSONResponse({"error": "instance thread not found"}, status_code=404)
        if not changed:
            return JSONResponse(
                {"error": "takeover not held by client"}, status_code=409
            )
        if heartbeat:
            queued = takeover.repository.queued_count(f"instance:{agent_id}")
            return JSONResponse({"ok": True, "queued": queued})
        return JSONResponse({"ok": True})

    return [
        Route(
            "/api/instance-threads/{agent_id:str}/takeover",
            post,
            methods=["POST"],
            name="user_only_instance_takeover",
        ),
        Route(
            "/api/instance-threads/{agent_id:str}/takeover",
            delete,
            methods=["DELETE"],
            name="user_only_instance_takeover_release",
        ),
        Route(
            "/api/instance-threads/{agent_id:str}/takeover/heartbeat",
            pulse,
            methods=["POST"],
            name="user_only_instance_takeover_heartbeat",
        ),
    ]


async def _get_supervisor(getter: Callable[[], Any]) -> Any:
    supervisor = getter()
    return await supervisor if hasattr(supervisor, "__await__") else supervisor


async def _payload(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        payload = await request.json()
    except json.JSONDecodeError, UnicodeDecodeError:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"error": "expected an object"}, status_code=400)
    return payload


def _client(payload: dict[str, Any]) -> str | None:
    client = payload.get("client")
    if not isinstance(client, str) or not client or client.startswith("system:"):
        return None
    return client
