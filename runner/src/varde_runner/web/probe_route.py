"""Workspace filesystem probe endpoint."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from varde_runner.service.probe import probe_paths


async def probe_route(request: Request) -> JSONResponse:
    """Probe known workspace directories without accepting caller paths."""
    registry: Any = request.app.state.registry
    paths: set[str] = set()
    for harness in registry.harnesses():
        for workspace in await registry.list_workspaces(harness):
            cwd = workspace.get("cwd")
            if isinstance(cwd, str) and cwd:
                paths.add(str(Path(cwd).expanduser()))
    results = await asyncio.to_thread(probe_paths, sorted(paths), 2.0)
    return JSONResponse(
        {
            "results": results,
            "message": (
                "A clean probe does not rule out other causes, including "
                "configuration or interpreter access."
            ),
        }
    )
