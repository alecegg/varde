"""`GET /api/bot/state` (bot-readable) and `POST /api/bot/control` (user only)."""

from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from varde_runner.bot_control import BotControl, ControlError

USER = "user"
ACTIONS = ("pause", "resume", "kill")


def create_bot_routes(control: BotControl) -> list[Route]:
    async def state(_: Request) -> JSONResponse:
        return JSONResponse(await control.snapshot())

    async def act(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except json.JSONDecodeError, UnicodeDecodeError:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        action = body.get("action") if isinstance(body, dict) else None
        if action not in ACTIONS:
            return JSONResponse(
                {"error": f"action must be one of {', '.join(ACTIONS)}"},
                status_code=400,
            )
        try:
            await getattr(control, action)(*_args(action))
        except ControlError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        return JSONResponse(await control.snapshot())

    return [
        Route("/api/bot/state", state, methods=["GET"]),
        Route("/api/bot/control", act, methods=["POST"]),
    ]


def _args(action: str) -> tuple[str, ...]:
    return ("paused by user", USER) if action == "pause" else (USER,)
