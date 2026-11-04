"""The daemon's ASGI app: request gate, health, login and shutdown."""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import BaseRoute, Route
from starlette.types import ASGIApp, Receive, Send
from starlette.types import Scope as AsgiScope

from varde_serve.daemon.config import ServeConfig
from varde_serve.daemon.security import (
    PerClientLimiter,
    RouteClass,
    Scope,
    allowed_hosts,
    host_ok,
    origin_ok,
    route_class,
    scope_denied,
    token_scope,
    write_denied,
)
from varde_serve.daemon.tokens import Tokens
from varde_serve.events.buffer import EventBuffer
from varde_serve.events.routes import event_routes
from varde_serve.events.watchers import Watcher, poll_loop

API_VERSION = 1
COOKIE = "varde_serve"
MAX_STREAMS = 16
STATUS = {
    "unauthorized": 401,
    "forbidden": 403,
    "edit_disabled": 403,
    "bad_host": 403,
    "bad_origin": 403,
    "human_only": 403,
    "rate_limited": 429,
    "method_not_allowed": 405,
    "too_many_streams": 429,
}


@dataclass
class DaemonContext:
    config: ServeConfig
    tokens: Tokens
    version: str
    port: int
    features: list[str] = field(default_factory=list)
    periodic_jobs: list[Callable[[], None]] = field(default_factory=list)
    extra_routes: list[BaseRoute] = field(default_factory=list)
    on_shutdown: Callable[[], None] = lambda: None
    on_stopped: Callable[[], None] = lambda: None
    last_request: float = field(default_factory=time.monotonic)
    open_streams: int = 0
    limiter: PerClientLimiter = field(default_factory=PerClientLimiter)
    events: EventBuffer = field(default_factory=EventBuffer)
    watchers: list[Watcher] = field(default_factory=list)
    poll_s: float = 1.0
    static_dir: Path | None = None
    keepalive_s: float = 15.0

    @property
    def hosts(self) -> frozenset[str]:
        return allowed_hosts(self.port, self.config.hosts)

    def idle_for(self) -> float:
        if self.open_streams:
            return 0.0
        return time.monotonic() - self.last_request


def error_body(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def refuse(code: str) -> JSONResponse:
    status = STATUS[code]
    return JSONResponse(error_body(code, code.replace("_", " ")), status_code=status)


def presented_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    jar: SimpleCookie = SimpleCookie()
    jar.load(request.headers.get("cookie", ""))
    morsel = jar.get(COOKIE)
    return morsel.value if morsel else ""


def gate(request: Request, ctx: DaemonContext) -> Response | None:
    """Return a refusal, or None when the request may proceed."""
    method, path = request.method, request.url.path
    if method == "OPTIONS":
        return refuse("method_not_allowed")
    if not host_ok(request.headers.get("host"), ctx.hosts):
        return refuse("bad_host")
    mutating = method in {"POST", "PUT", "DELETE", "PATCH"}
    if (mutating or path.startswith("/api/events")) and not origin_ok(
        request.headers.get("origin"), ctx.hosts
    ):
        return refuse("bad_origin")
    klass = route_class(method, path)
    if klass is RouteClass.PUBLIC:
        return None
    scope = token_scope(presented_token(request), ctx.tokens.human, ctx.tokens.mcp)
    if scope is None:
        return refuse("unauthorized")
    if scope_denied(klass, scope):
        return refuse("human_only")
    cookie_without_origin = (
        mutating
        and "cookie" in request.headers
        and "origin" not in request.headers
        and not request.headers.get("authorization")
    )
    if cookie_without_origin:
        return refuse("bad_origin")
    denial = write_denied(path, True, ctx.config.allow_edit) if mutating else None
    return refuse(denial) if denial else None


class GateMiddleware:
    def __init__(self, app: ASGIApp, ctx: DaemonContext) -> None:
        self.app = app
        self.ctx = ctx

    async def __call__(self, scope: AsgiScope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        self.ctx.last_request = time.monotonic()
        refusal = gate(Request(scope, receive), self.ctx)
        if refusal is not None:
            await refusal(scope, receive, send)
            return
        await self.app(scope, receive, send)


@contextlib.asynccontextmanager
async def _lifespan(ctx: DaemonContext) -> AsyncIterator[None]:
    task = asyncio.create_task(poll_loop(ctx.events, ctx.watchers, ctx.poll_s))
    try:
        yield
    finally:
        task.cancel()
        ctx.on_stopped()


def build_app(ctx: DaemonContext) -> Starlette:
    async def health(request: Request) -> Response:
        body = {
            "version": ctx.version,
            "api_version": API_VERSION,
            "features": ctx.features,
            "pid": os.getpid(),
        }
        return JSONResponse(body)

    async def shutdown(request: Request) -> Response:
        ctx.on_shutdown()
        return JSONResponse({"stopping": True})

    async def login(request: Request) -> Response:
        return HTMLResponse(
            "<!doctype html><title>varde serve</title>"
            '<form method="post" action="/auth/session" onsubmit="return false">'
            '<input id="token" type="password" placeholder="token"></form>'
        )

    async def root(request: Request) -> Response:
        return HTMLResponse(
            "<!doctype html><title>varde serve</title><p>varde serve</p>"
        )

    async def session(request: Request) -> Response:
        client = request.client.host if request.client else ""
        if ctx.limiter.blocked(client):
            return refuse("rate_limited")
        try:
            sent = (await request.json()).get("token", "")
        except ValueError, AttributeError:
            sent = ""
        if token_scope(str(sent), ctx.tokens.human, ctx.tokens.mcp) is not Scope.HUMAN:
            ctx.limiter.record_failure(client)
            return refuse("unauthorized")
        response = JSONResponse({"ok": True})
        response.set_cookie(
            COOKIE, str(sent), httponly=True, samesite="strict", path="/"
        )
        return response

    routes: list[BaseRoute] = [
        Route("/health", health),
        Route("/shutdown", shutdown, methods=["POST"]),
        Route("/login", login),
        Route("/auth/session", session, methods=["POST"]),
        Route("/", root),
        *event_routes(ctx),
        *ctx.extra_routes,
    ]
    app = Starlette(routes=routes, lifespan=lambda _app: _lifespan(ctx))
    app.add_middleware(GateMiddleware, ctx=ctx)
    return app


__all__ = ["API_VERSION", "MAX_STREAMS", "DaemonContext", "build_app"]
