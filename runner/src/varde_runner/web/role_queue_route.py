"""Home and per-role summaries for the queue page.

Serves ``RoleSummary`` and ``RoleQueueRow`` payloads built by
``role_queue_source.read_role_queue`` on ``GET /api/home`` and
``GET /api/queue/roles/{role}``. The queue page (``homeApi.ts``,
``RoleStatusCard.svelte``, ``queue/[role]/+page.svelte``) is its only consumer;
raw store rows, budget, and metrics are ``role_queues_route.py``.
"""

from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from varde_data.errors import Invalid

from varde_runner.config import ROLE_NAMES, config_dir
from varde_runner.identity_profile import defaults
from varde_runner.registry import SessionRegistry
from varde_runner.role_queue import home_sort
from varde_runner.role_queue_source import read_role_queue
from varde_runner.web.agents_route import _agent_rows, _supervisor
from varde_runner.web.identities_route import _profiles


def create_role_queue_routes(dashboard: Any, get_supervisor: Any) -> list[Route]:
    async def role_queues(request: Request) -> JSONResponse:
        try:
            queues = await _read_queues()
        except Invalid as error:
            return JSONResponse({"error": str(error)}, status_code=503)
        return JSONResponse(
            {"roles": [asdict(role) for role in home_sort(queues.roles)]}
        )

    async def role_queue(request: Request) -> JSONResponse:
        role = request.path_params["role"]
        try:
            queues = await _read_queues()
        except Invalid as error:
            return JSONResponse({"error": str(error)}, status_code=503)
        summary = next((item for item in queues.roles if item.role == role), None)
        if summary is None:
            return JSONResponse({"error": "unknown role"}, status_code=404)
        return JSONResponse(
            {
                "summary": asdict(summary),
                "rows": [asdict(row) for row in queues.rows.get(role, [])],
            }
        )

    async def _read_queues():
        supervisor = await _supervisor(get_supervisor)
        directory = config_dir() / "identities"
        sources = SimpleNamespace(
            queue_inputs=dashboard.queue_inputs,
            agent_rows=await _agent_rows(supervisor),
            bindings=SessionRegistry(
                supervisor.data_dir / "registry.json"
            ).bindings_by_session_id(),
            profiles=(
                _profiles(directory)[0] if directory.exists() else defaults(ROLE_NAMES)
            ),
        )
        return read_role_queue(sources)

    return [
        Route("/api/home", role_queues),
        Route("/api/queue/roles/{role:str}", role_queue),
    ]
