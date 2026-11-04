"""HTTP routes: parse the request, call one handler, shape the response."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import BaseRoute, Route
from varde_data.errors import Invalid
from varde_learn.docs.pages.serve import render_document

from varde_serve.api import read, write
from varde_serve.api.docs import list_docs, read_doc, resolve_doc
from varde_serve.api.errors import ApiError
from varde_serve.api.static import static_route
from varde_serve.daemon.security import (
    WRITE_METHODS,
    RouteClass,
    WriteRoute,
    set_write_routes,
)
from varde_serve.project import Project

if TYPE_CHECKING:
    from varde_serve.daemon.app import DaemonContext

MAX_LIMIT = 200
DEFAULT_LIMIT = 50
Handler = Callable[[Request], dict[str, Any]]


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}}, status_code=status
    )


def bounded_limit(request: Request, ceiling: int = MAX_LIMIT) -> int:
    try:
        wanted = int(request.query_params.get("limit", DEFAULT_LIMIT))
    except ValueError:
        wanted = DEFAULT_LIMIT
    return max(1, min(ceiling, wanted))


async def body_of(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError:
        raise ApiError(400, "bad_request", "body must be JSON") from None
    if not isinstance(body, dict):
        raise ApiError(400, "bad_request", "body must be a JSON object")
    return body


def text_field(body: dict[str, Any], name: str) -> str:
    value = body.get(name)
    if not isinstance(value, str):
        raise ApiError(400, "bad_request", f"{name} must be a string")
    return value


def endpoint(handler: Callable[[Request], Any], status: int = 200):
    """Run a (possibly blocking) handler off the event loop; map errors."""

    async def respond(request: Request) -> Response:
        try:
            result = handler(request)
            if asyncio.iscoroutine(result):
                result = await result
            if callable(result):
                result = await asyncio.to_thread(result)
        except ApiError as error:
            return error_response(error.status, error.code, error.message)
        except Invalid as error:
            return error_response(400, "bad_request", str(error))
        if isinstance(result, Response):
            return result
        return JSONResponse(result, status_code=status)

    return respond


class Endpoints:
    def __init__(self, project: Project) -> None:
        self.project = project

    def plans(self, request: Request):
        return lambda: read.get_plans(self.project)

    def plan(self, request: Request):
        return lambda: read.get_plan(self.project, request.path_params["plan_id"])

    def task(self, request: Request):
        params = request.path_params
        return lambda: read.get_task(self.project, params["plan_id"], params["task"])

    def queue(self, request: Request):
        return lambda: read.get_queue(self.project)

    def reorder(self, request: Request):
        return lambda: write.reorder_queue(self.project)

    def friction(self, request: Request):
        query = request.query_params
        limit = bounded_limit(request, 1000)
        return lambda: read.get_friction(
            self.project, query.get("status"), query.get("tag"), limit
        )

    async def friction_add(self, request: Request):
        body = await body_of(request)
        tags = body.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ApiError(400, "bad_request", "tags must be a list of strings")
        text = text_field(body, "text")
        return lambda: write.add_friction(self.project, text, tags)

    def docs(self, request: Request):
        return lambda: {"docs": list_docs(self.project)}

    def doc(self, request: Request):
        return lambda: read_doc(self.project, request.path_params["path"])

    def page(self, request: Request):
        def render() -> Response:
            found = resolve_doc(self.project, request.path_params["path"])
            return HTMLResponse(render_document(found, ""))

        return render

    async def comment(self, request: Request):
        body = await body_of(request)
        return lambda: write.add_comment(
            self.project, request.path_params["path"], body
        )

    async def reply(self, request: Request):
        text = text_field(await body_of(request), "text")
        params = request.path_params
        return lambda: write.add_reply(
            self.project, params["path"], params["cid"], text
        )

    async def decision(self, request: Request):
        answer = text_field(await body_of(request), "answer")
        params = request.path_params
        return lambda: write.answer_decision(
            self.project, params["path"], params["did"], answer
        )

    def mail(self, request: Request):
        return lambda: read.get_mail(self.project)

    async def mail_send(self, request: Request):
        body = await body_of(request)
        fields = [text_field(body, n) for n in ("to", "kind", "text")]
        return lambda: write.send_mail(self.project, *fields)

    def search(self, request: Request):
        query = request.query_params
        needle = query.get("q", "").strip()
        if not needle:
            raise ApiError(400, "bad_request", "q is required")
        limit = bounded_limit(request, 50)
        return lambda: read.search(self.project, needle, query.get("domain"), limit)

    def config(self, request: Request):
        return lambda: read.get_config(self.project)

    async def config_set(self, request: Request):
        body = await body_of(request)
        if "value" not in body:
            raise ApiError(400, "bad_request", "value is required")
        return lambda: write.set_config(
            self.project, request.path_params["key"], body["value"]
        )


def api_routes(ctx: DaemonContext, project: Project) -> list[BaseRoute]:
    e = Endpoints(project)
    classes: list[WriteRoute] = []

    def route(
        path: str,
        handler: Callable,
        methods: list[str],
        status: int = 200,
        klass: RouteClass = RouteClass.HUMAN_WRITE,  # unlisted writes fail closed
    ) -> Route:
        found = Route(path, endpoint(handler, status), methods=methods)
        writes = frozenset(methods) & WRITE_METHODS
        if writes:
            classes.append((writes, found.path_regex, klass))
        return found

    agent = RouteClass.AGENT_WRITE
    routes: list[BaseRoute] = [
        route("/api/plans", e.plans, ["GET"]),
        route("/api/plans/{plan_id}", e.plan, ["GET"]),
        route("/api/plans/{plan_id}/tasks/{task}", e.task, ["GET"]),
        route("/api/queue", e.queue, ["GET"]),
        route("/api/queue/reorder", e.reorder, ["POST"]),
        route("/api/friction", e.friction, ["GET"]),
        route("/api/friction", e.friction_add, ["POST"], 201, agent),
        route("/api/docs", e.docs, ["GET"]),
        route(
            "/api/docs/{path:path}/comments/{cid}/replies",
            e.reply,
            ["POST"],
            201,
            agent,
        ),
        route("/api/docs/{path:path}/comments", e.comment, ["POST"], 201, agent),
        route("/api/docs/{path:path}/decisions/{did}", e.decision, ["POST"], 201),
        route("/api/docs/{path:path}", e.doc, ["GET"]),
        route("/pages/{path:path}", e.page, ["GET"]),
        route("/api/mail", e.mail, ["GET"]),
        route("/api/mail", e.mail_send, ["POST"], 201, agent),
        route("/api/search", e.search, ["GET"]),
        route("/api/config", e.config, ["GET"]),
        route("/api/config/{key}", e.config_set, ["PUT"]),
        *static_route(ctx),
    ]
    set_write_routes(classes)
    return routes
