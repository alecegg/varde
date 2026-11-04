"""HTTP routes for managing native agent sessions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from varde_runner.agent_launch import (
    AgentLaunchError,
    DisabledHarnessError,
    launch_agent,
)
from varde_runner.bot_taint import bot_visible_rows, root_launched_by
from varde_runner.clients import ObserverReadOnly, UnknownClient
from varde_runner.instance_cap import InstanceCapError
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.protocol import UnsupportedCapability
from varde_runner.supervisor import SendOutcome, Supervisor

WRITE_ACTIONS = ("prompt", "interrupt", "respond", "resume", "stop", "archive", "mode")


def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


async def _agent_rows(supervisor: Supervisor) -> list[dict[str, Any]]:
    waits: dict[str, list[dict[str, str]]] = {}
    pending_counts: dict[str, int] = {}
    for wait in supervisor.approval_waits_for_mailbox():
        agent_id = str(wait.get("session_id", ""))
        if wait.get("state") == "pending":
            pending_counts[agent_id] = pending_counts.get(agent_id, 0) + 1
        waits.setdefault(agent_id, []).append(
            {
                "request_id": str(wait.get("payload", {}).get("request_id", "")),
                "kind": str(wait.get("kind", "approval")),
                "summary": str(
                    wait.get("summary")
                    or wait.get("payload", {}).get("summary")
                    or wait.get("agent_title", "")
                ),
            }
        )
    rows = []
    for row in supervisor.store.sessions():
        harness = str(row.get("harness", row.get("backend", "")))
        plugin = supervisor.registry.plugin_for_key(str(row.get("backend", "")))
        session_id = str(row["id"])
        liveness = await supervisor.liveness(
            session_id, pending_approvals=pending_counts.get(session_id, 0)
        )
        rows.append(
            {
                "agent_id": str(row.get("agent_id", row["id"])),
                "session_id": str(row["id"]),
                "harness": harness,
                "role": row.get("role"),
                "parent_id": row.get("parent_id"),
                "launched_by": row.get("launched_by"),
                "root_launched_by": root_launched_by(row.get("launched_by")),
                "workspace": row.get("workspace_id"),
                "lifecycle": row.get("lifecycle"),
                "idle_status": row.get("idle_status"),
                "liveness": liveness.state,
                "liveness_reason": liveness.reason,
                "capabilities": asdict(plugin.capabilities) if plugin else {},
                "pending_requests": waits.get(str(row["id"]), []),
            }
        )
    return rows


def agent_capabilities(registry: PluginRegistry) -> dict[str, Any]:
    return {
        **{
            harness: asdict(registry.capabilities(harness))
            for harness in sorted(registry.harnesses())
        },
        "disabled": sorted(registry.known_harnesses() - registry.harnesses()),
    }


async def _supervisor(get_supervisor: Callable[[], Any]) -> Supervisor:
    result = get_supervisor()
    if hasattr(result, "__await__"):
        result = await result
    return result


async def _json_object(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        payload = await request.json()
    except ValueError, UnicodeDecodeError:
        return _error("invalid JSON body", 400)
    if not isinstance(payload, dict):
        return _error("invalid JSON body", 400)
    return payload


def _writer_client(payload: dict[str, Any]) -> str | JSONResponse:
    client = payload.get("client")
    if not isinstance(client, str) or not client or client.startswith("system:"):
        return _error("invalid client", 400)
    return client


def _agent_or_404(
    supervisor: Supervisor, agent_id: str
) -> dict[str, Any] | JSONResponse:
    row = supervisor.resolve_session(agent_id)
    return row if row is not None else _error("agent not found", 404)


def _write_error(error: Exception) -> JSONResponse:
    if isinstance(error, (UnknownClient, ObserverReadOnly)):
        return _error("write client is not authorized", 409)
    if isinstance(error, UnsupportedCapability):
        return _error(str(error), 501)
    return _error("agent action failed", 409)


def _launched_by(request: Request) -> str | None:
    """The gateway-set identity of a bot-rooted caller; clients cannot supply it."""
    identity = request.scope.get("bot_identity")
    return identity.actor if identity is not None else None


def _record_identity_fallback(
    request: Request,
    requested_identity: Any,
    role: str,
    agent_id: str,
    record: Callable[[str], None] | None,
) -> None:
    if (
        request.scope.get("bot_identity") is not None
        and isinstance(requested_identity, str)
        and requested_identity != role
        and record is not None
    ):
        record(agent_id)


def _launch_payload_error(payload: dict[str, Any]) -> JSONResponse | None:
    required = ("workspace", "role", "prompt")
    if any(
        not isinstance(payload.get(key), str) or not payload[key] for key in required
    ):
        return _error("workspace, role and prompt are required", 400)
    optional = ("harness", "mode", "parent_id")
    if any(
        payload.get(key) is not None
        and (not isinstance(payload[key], str) or not payload[key])
        for key in optional
    ):
        return _error("harness, mode and parent_id must be non-empty strings", 400)
    address = payload.get("address")
    if address is not None and (
        not isinstance(address, dict)
        or not isinstance(address.get("slot"), str)
        or not address["slot"]
        or (
            address.get("plan") is not None
            and (not isinstance(address["plan"], str) or not address["plan"])
        )
    ):
        return _error("address must contain a slot and optional plan", 400)
    return None


def create_agents_routes(
    get_supervisor: Callable[[], Any],
    *,
    on_identity_fallback: Callable[[str], None] | None = None,
) -> list[Route]:
    async def agents(request: Request) -> JSONResponse:
        supervisor = await _supervisor(get_supervisor)
        rows = await _agent_rows(supervisor)
        identity = request.scope.get("bot_identity")
        if identity is not None:
            rows = bot_visible_rows(identity.actor, rows)
        parent = request.query_params.get("parent")
        if parent:
            rows = [row for row in rows if row["parent_id"] == parent]
        return JSONResponse(rows)

    async def launch(request: Request) -> JSONResponse:
        payload = await _json_object(request)
        if isinstance(payload, JSONResponse):
            return payload
        invalid = _launch_payload_error(payload)
        if invalid is not None:
            return invalid
        address = payload.get("address")
        address_request = (
            {"slot": address["slot"], "plan": address.get("plan")}
            if isinstance(address, dict)
            else None
        )
        supervisor = await _supervisor(get_supervisor)
        try:
            ref = await launch_agent(
                supervisor,
                payload.get("harness"),
                payload["workspace"],
                payload["role"],
                payload["prompt"],
                address_request,
                mode=payload.get("mode"),
                parent_id=payload.get("parent_id"),
                launched_by=_launched_by(request),
            )
        except InstanceCapError as exc:
            return JSONResponse(
                {"error": "instance_cap", "live": exc.live, "max": exc.max_live},
                status_code=409,
            )
        except DisabledHarnessError as exc:
            return _error(str(exc), 409)
        except AgentLaunchError as exc:
            return _error(str(exc), 400)
        _record_identity_fallback(
            request,
            payload.get("requested_identity"),
            payload["role"],
            ref.session_id,
            on_identity_fallback,
        )
        return JSONResponse({"agent_id": ref.session_id}, status_code=201)

    async def write(request: Request, action: str) -> JSONResponse:
        if action not in WRITE_ACTIONS:
            return _error("unknown agent action", 404)
        agent_id = request.path_params["id"]
        supervisor = await _supervisor(get_supervisor)
        row = _agent_or_404(supervisor, agent_id)
        if isinstance(row, JSONResponse):
            return row
        payload = await _json_object(request)
        if isinstance(payload, JSONResponse):
            return payload
        client = _writer_client(payload)
        if isinstance(client, JSONResponse):
            return client
        if action == "mode":
            return await _mode_with_client(supervisor, agent_id, payload, client)
        return await _write_with_client(supervisor, agent_id, action, payload, client)

    def action_route(action: str) -> Route:
        async def endpoint(request: Request) -> JSONResponse:
            return await write(request, action)

        return Route(f"/api/agents/{{id:str}}/{action}", endpoint, methods=["POST"])

    async def unknown_action(request: Request) -> JSONResponse:
        return _error("unknown agent action", 404)

    return [
        Route("/api/agents", agents, methods=["GET"]),
        Route("/api/agents", launch, methods=["POST"]),
        *[action_route(action) for action in WRITE_ACTIONS],
        Route("/api/agents/{id:str}/{action:str}", unknown_action, methods=["POST"]),
    ]


async def _write_with_client(
    supervisor: Supervisor,
    agent_id: str,
    action: str,
    payload: dict[str, Any],
    client: str,
) -> JSONResponse:
    if action in {"resume", "stop", "archive"}:
        return await _lifecycle_with_client(supervisor, agent_id, action, client)
    try:
        if action == "prompt":
            text = payload.get("text")
            if not isinstance(text, str) or not text:
                return _error("text is required", 400)
            outcome = await supervisor.send(agent_id, text, client_id=client)
            return JSONResponse({"outcome": outcome.value})
        if action == "interrupt":
            result = await supervisor.interrupt(agent_id, client)
            if result == SendOutcome.FAILED_INTERRUPT:
                return _error("failed_interrupt", 409)
            return JSONResponse({"outcome": "interrupted"})
        request_id, decision = payload.get("request_id"), payload.get("decision")
        if (
            not isinstance(request_id, str)
            or not request_id
            or not isinstance(decision, str)
            or not decision
        ):
            return _error("request_id and decision are required", 400)
        result = await supervisor.respond(
            agent_id, request_id, decision, client_id=client
        )
    except (KeyError, PermissionError, RuntimeError, UnsupportedCapability) as exc:
        return _write_error(exc)
    status = 200 if result == "responded" else 501 if result == "unsupported" else 409
    return JSONResponse({"result": result}, status_code=status)


async def _lifecycle_with_client(
    supervisor: Supervisor, agent_id: str, action: str, client: str
) -> JSONResponse:
    try:
        if action == "stop":
            await supervisor.stop(agent_id, client)
        elif action == "archive":
            await supervisor.archive(agent_id, client)
        else:
            await supervisor.resume(agent_id, client)
    except (KeyError, PermissionError, RuntimeError, UnsupportedCapability) as exc:
        return _write_error(exc)
    return JSONResponse({})


async def _mode_with_client(
    supervisor: Supervisor, agent_id: str, payload: dict[str, Any], client: str
) -> JSONResponse:
    mode = payload.get("mode")
    if not isinstance(mode, str) or not mode:
        return _error("mode is required", 400)
    try:
        await supervisor.set_mode(agent_id, client, mode)
    except ValueError as exc:
        return _error(str(exc), 400)
    except UnsupportedCapability as exc:
        return _error(str(exc), 501)
    except (KeyError, PermissionError, RuntimeError) as exc:
        return _write_error(exc)
    return JSONResponse({"mode": mode})
