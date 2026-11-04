"""Decision metrics API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from varde_runner.decision_metrics import SUPPORTED_GROUPS, candidates, summarize


async def decision_metrics(request: Request) -> JSONResponse:
    group_by = request.query_params.get("group_by", "role")
    if group_by not in SUPPORTED_GROUPS:
        return JSONResponse({"error": "invalid group_by"}, status_code=400)
    since = request.query_params.get("since")
    if since is not None:
        try:
            parsed_since = datetime.fromisoformat(since)
        except ValueError:
            return JSONResponse({"error": "invalid since"}, status_code=400)
        if parsed_since.tzinfo is None:
            parsed_since = parsed_since.replace(tzinfo=UTC)
        since = parsed_since.astimezone(UTC).isoformat()
    getter: Any = request.app.state.dashboard.supervisor_getter
    if getter is None:
        return JSONResponse({"error": "supervisor unavailable"}, status_code=503)
    supervisor = await getter()
    rows = supervisor.store.decision_events()
    return JSONResponse(
        {"groups": summarize(rows, group_by, since), "candidates": candidates(rows)}
    )
