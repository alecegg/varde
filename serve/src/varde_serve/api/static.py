"""`/static/*`: files from `ctx.static_dir` when serve-gui supplies one."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import FileResponse, Response
from starlette.routing import BaseRoute, Route

if TYPE_CHECKING:
    from varde_serve.daemon.app import DaemonContext


def static_route(ctx: DaemonContext) -> list[BaseRoute]:
    async def serve_file(request: Request) -> Response:
        root = ctx.static_dir
        if root is None:
            return Response("not found", status_code=404)
        target = (root / request.path_params["name"]).resolve()
        if not (target.is_relative_to(root.resolve()) and target.is_file()):
            return Response("not found", status_code=404)
        return FileResponse(target)

    return [Route("/static/{name:path}", serve_file)]
