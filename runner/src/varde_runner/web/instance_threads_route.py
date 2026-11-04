"""Read-only API for per-agent conversation threads."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from varde_runner.instance_threads import InstanceThreads


def create_instance_threads_routes(
    service: InstanceThreads, get_supervisor: Callable[[], Any]
) -> list[Route]:
    async def instance_threads(request: Request) -> JSONResponse:
        plan_id = request.query_params.get("plan")
        agent_id = request.query_params.get("agent")
        if plan_id == "" or agent_id == "" or (plan_id and agent_id):
            return JSONResponse(
                {"error": "provide one non-empty plan or agent filter"},
                status_code=400,
            )
        supervisor = get_supervisor()
        if hasattr(supervisor, "__await__"):
            supervisor = await supervisor
        rows = await service.refresh(supervisor)
        if agent_id:
            rows = [row for row in rows if row["agent_id"] == agent_id]
            if not rows:
                return JSONResponse({"error": "agent not found"}, status_code=404)
        elif plan_id:
            rows = [row for row in rows if row["plan_id"] == plan_id]
        else:
            rows = sorted(
                rows,
                key=lambda row: (
                    row["plan_id"] is None,
                    str(row["plan_id"] or "").casefold(),
                    str(row["label"] or "").casefold(),
                ),
            )
        return JSONResponse({"threads": rows})

    return [Route("/api/instance-threads", instance_threads, methods=["GET"])]


def plan_ids_from_working_dir(working_dir: str | None) -> Sequence[str]:
    """Read plan directory names used to resolve task worktree names."""
    if not working_dir:
        return ()
    plans = Path(working_dir) / "plans"
    try:
        return tuple(path.name for path in plans.iterdir() if path.is_dir())
    except OSError:
        return ()
