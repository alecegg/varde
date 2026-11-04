"""Mailbox thread list route."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from varde_runner.web.queue import _plan_metadata


async def _threads(request: Request) -> JSONResponse:
    dashboard: Any = request.app.state.dashboard
    return JSONResponse(await dashboard.mailbox_threads())


async def _degraded(request: Request) -> JSONResponse:
    dashboard: Any = request.app.state.dashboard
    return JSONResponse({"sources": dashboard.degraded_sources()})


def _plan_titles(working_dir: Path) -> dict[str, str]:
    plans, _, _, _ = _plan_metadata(working_dir, [])
    return {
        str(plan["id"]): str(plan.get("label") or plan["title"])
        for plan in plans
        if plan.get("id") and plan.get("title")
    }


def create_threads_routes(working_dir: Path) -> list[Route]:
    async def threads(request: Request) -> JSONResponse:
        return await _threads(request)

    return [Route("/api/threads", threads), Route("/api/degraded", _degraded)]
