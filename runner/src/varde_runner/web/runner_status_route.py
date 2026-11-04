"""Runner status and service-managed restart endpoints."""

from __future__ import annotations

import os
import signal
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from varde_runner.first_run import checklist
from varde_runner.runner_status import CommandRunner, build_status

ROUTE_POLICIES = {
    ("GET", "/api/runner/status"): "read",
    ("POST", "/api/runner/restart"): "user_only",
}


def create_runner_status_routes(
    registry_getter: Callable[[], Any],
    working_dir: Path,
    *,
    command_runner: CommandRunner | None = None,
    restart: Callable[[], None] | None = None,
) -> list[Route]:
    async def status(_request: Request) -> JSONResponse:
        if command_runner is None:
            result = build_status(registry_getter(), working_dir)
        else:
            result = build_status(
                registry_getter(), working_dir, command_runner=command_runner
            )
        result["checklist"] = checklist(result)
        return JSONResponse(result)

    async def restart_runner(_request: Request) -> JSONResponse:
        if os.environ.get("VARDE_RUNNER_SERVICE") not in {"launchd", "systemd"}:
            return JSONResponse(
                {
                    "error": "not_managed",
                    "hint": (
                        "Run `varde-runner service start` to start the installed "
                        "service."
                    ),
                },
                status_code=409,
            )
        stop = restart or (lambda: os.kill(os.getpid(), signal.SIGTERM))
        return JSONResponse(
            {"status": "restarting"},
            status_code=202,
            background=BackgroundTask(stop),
        )

    return [
        Route("/api/runner/status", status, methods=["GET"], name="read_runner_status"),
        Route(
            "/api/runner/restart",
            restart_runner,
            methods=["POST"],
            name="user_only_runner_restart",
        ),
    ]
