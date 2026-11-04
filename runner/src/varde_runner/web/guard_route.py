"""Permission guard audit endpoints."""

from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from varde_runner.guard_log import approvals_by_pattern, redact_prompt


async def verdicts(request: Request) -> JSONResponse:
    limit_text = request.query_params.get("limit", "100")
    before_text = request.query_params.get("before")
    try:
        limit = int(limit_text)
        before = int(before_text) if before_text is not None else None
    except ValueError:
        return JSONResponse({"error": "invalid pagination"}, status_code=400)
    if not 1 <= limit <= 500 or (before is not None and before <= 0):
        return JSONResponse({"error": "invalid pagination"}, status_code=400)
    supervisor = await request.app.state.dashboard.supervisor_getter()
    rows = supervisor.store.guard_verdicts(limit, before)
    fields = (
        "id",
        "ts",
        "request_key",
        "request_kind",
        "prompt",
        "verdict",
        "reason",
        "escalated",
    )
    return JSONResponse(
        {
            "verdicts": [
                {
                    field: redact_prompt(row[field])
                    if field in {"prompt", "reason"}
                    else row[field]
                    for field in fields
                }
                for row in rows
            ]
        }
    )


async def approvals(request: Request) -> JSONResponse:
    supervisor = await request.app.state.dashboard.supervisor_getter()
    store = supervisor.store
    rows = []
    before = None
    while True:
        page = store.guard_verdicts(500, before)
        rows.extend(page)
        if len(page) < 500:
            break
        before = page[-1]["id"]
    revoked = store.revoked_guard_patterns()
    patterns = approvals_by_pattern(rows, revoked)
    present = {item["request_key"] for item in patterns}
    patterns.extend(
        {"request_key": key, "count": 0, "last_ts": "", "revoked": True}
        for key in revoked - present
    )
    return JSONResponse(
        {"approvals": sorted(patterns, key=lambda item: item["request_key"])}
    )


async def revoke(request: Request) -> JSONResponse:
    return await _set_revocation(request, revoked=True)


async def unrevoke(request: Request) -> JSONResponse:
    return await _set_revocation(request, revoked=False)


async def _set_revocation(request: Request, *, revoked: bool) -> JSONResponse:
    try:
        payload = await request.json()
    except json.JSONDecodeError, UnicodeDecodeError:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    key = payload.get("request_key") if isinstance(payload, dict) else None
    if not isinstance(key, str) or not key or len(key) > 500:
        return JSONResponse(
            {"error": "request_key must be a non-empty string"}, status_code=400
        )
    supervisor = await request.app.state.dashboard.supervisor_getter()
    if revoked:
        supervisor.store.revoke_guard_pattern(key)
    else:
        supervisor.store.unrevoke_guard_pattern(key)
    return JSONResponse({"request_key": key, "revoked": revoked})


def guard_routes() -> list[Route]:
    return [
        Route("/api/guard/verdicts", verdicts),
        Route("/api/guard/approvals", approvals),
        Route("/api/guard/revoke", revoke, methods=["POST"]),
        Route("/api/guard/unrevoke", unrevoke, methods=["POST"]),
    ]
