"""`GET /api/bot/audit`: newest-first audit rows, readable by the bot."""

from __future__ import annotations

from dataclasses import asdict

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from varde_runner.bot_audit import BotAudit


def _int_param(request: Request, name: str) -> int | None:
    value = request.query_params.get(name)
    return int(value) if value is not None and value.isdecimal() else None


def create_bot_audit_routes(audit: BotAudit) -> list[Route]:
    async def rows(request: Request) -> JSONResponse:
        limit = _int_param(request, "limit") or 50
        page = audit.repo.audit_page(_int_param(request, "before"), limit)
        return JSONResponse([asdict(row) for row in page])

    return [Route("/api/bot/audit", rows, methods=["GET"])]
