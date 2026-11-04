"""Read-only task build-queue route for a plan."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from varde_data.errors import Invalid
from varde_data.queue import open_queue
from varde_data.queue_line_sync import line_queue_name
from varde_data.queue_mode_lock import operation
from varde_workflow.queue_check import check_queue


def _latest_context_tokens(store: Any, session_id: str) -> int | None:
    row = store.connection.execute(
        "SELECT payload FROM events WHERE session_id = ? AND kind = 'usage' "
        "ORDER BY seq DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(row[0])
    except json.JSONDecodeError, TypeError:
        return None
    if not isinstance(payload, dict):
        return None
    context_tokens = payload.get("context_tokens")
    if not isinstance(context_tokens, int) or isinstance(context_tokens, bool):
        return None
    return context_tokens


def _context_tokens(supervisor: Any, worktrees: set[str]) -> list[dict[str, Any]]:
    rows = []
    for session in supervisor.store.sessions():
        role = session.get("role")
        if role not in {"builder", "reviewer"}:
            continue
        workspace = session.get("workspace_id")
        if not isinstance(workspace, str) or workspace not in worktrees:
            continue
        usage = _latest_context_tokens(supervisor.store, session["id"])
        rows.append(
            {
                "role": role,
                "session_id": session["id"],
                "worktree": workspace,
                "context_tokens": usage,
            }
        )
    return rows


def create_task_queue_routes(
    working_dir: Path, get_supervisor: Callable[[], Any]
) -> list[Route]:
    queue_cache: tuple[object, list[Any]] | None = None

    async def task_queue(request: Request) -> JSONResponse:
        nonlocal queue_cache
        plan_id = request.path_params["plan_id"]
        if not plan_id or Path(plan_id).name != plan_id:
            return JSONResponse({"error": "invalid plan id"}, status_code=400)
        plan_dir = working_dir / "plans" / plan_id
        if not (plan_dir / "plan.md").is_file():
            return JSONResponse({"error": "plan not found"}, status_code=404)
        queue_path = plan_dir / "notes" / "queue.md"
        try:
            with operation(working_dir) as mode:
                if mode == "markdown" and not queue_path.is_file():
                    queue = {
                        "plan": str(plan_dir),
                        "plan_id": plan_id,
                        "items": [],
                    }
                    rows = []
                else:
                    queue = check_queue(plan_dir)
                    rows = []
                    if mode == "sqlite":
                        repository = open_queue(working_dir)
                        version = repository.version()
                        if queue_cache is None or queue_cache[0] != version:
                            queue_cache = (version, repository.list())
                        queue_name = line_queue_name(plan_dir)
                        rows = [
                            row
                            for row in queue_cache[1]
                            if row.queue_name == queue_name
                        ]
        except Invalid as error:
            return JSONResponse({"error": str(error)}, status_code=503)
        except (OSError, TypeError, ValueError) as error:
            return JSONResponse({"error": str(error)}, status_code=422)

        claims = {
            str((row.extra or {}).get("task", row.id.rsplit("#", 1)[-1])): row
            for row in rows
        }
        queue["items"] = [
            item
            | {
                "claimed_by": claims[item["task_id"]].claimed_by
                if item["task_id"] in claims
                else None,
                "claim_expires_at": claims[item["task_id"]].claim_expires_at
                if item["task_id"] in claims
                else None,
            }
            for item in queue["items"]
        ]

        supervisor = get_supervisor()
        if hasattr(supervisor, "__await__"):
            supervisor = await supervisor
        worktrees = {
            item["worktree"] for item in queue["items"] if item["worktree"] != "-"
        }
        return JSONResponse(
            queue | {"role_sessions": _context_tokens(supervisor, worktrees)}
        )

    return [Route("/api/plans/{plan_id:str}/task-queue", task_queue)]
