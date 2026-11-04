"""Pairing routes and the gate that makes `user_only` routes need the user cookie."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from http.cookies import SimpleCookie

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from varde_runner.bot_route_policy import Kind, classify
from varde_runner.user_credential import (
    COOKIE_NAME,
    COOKIE_TTL_SECONDS,
    CSRF_HEADER,
    UserCredential,
)

PAIRING_PATH = "/api/pairing"
PAIRING_ROUTE_KEY = f"POST {PAIRING_PATH}"
REFUSED = "this route needs the paired user browser"


def _scope_header(scope: Scope, name: str) -> str | None:
    for key, value in scope.get("headers", ()):
        if key.decode("latin-1").lower() == name:
            return value.decode("latin-1")
    return None


def cookie_secure(scheme: str, headers: Mapping[str, str]) -> bool:
    """Secure for HTTPS, direct or behind a loopback TLS proxy (Tailscale Serve)."""
    forwarded = headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return scheme == "https" or forwarded == "https"


def cookie_from(raw: str | None) -> str | None:
    if not raw:
        return None
    jar: SimpleCookie = SimpleCookie()
    try:
        jar.load(raw)
    except Exception:  # noqa: BLE001 - a malformed Cookie header is just no cookie
        return None
    morsel = jar.get(COOKIE_NAME)
    return morsel.value if morsel else None


class UserCredentialGate:
    """Refuse a `user_only` write unless it has the paired cookie and CSRF header."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        credential: UserCredential,
        routes: Callable[[], Sequence[BaseRoute]],
        require_user_pairing: bool = True,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.app = app
        self.credential = credential
        self.routes = routes
        self.require_user_pairing = require_user_pairing
        self.clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self._needs_user(scope):
            cookie = cookie_from(_scope_header(scope, "cookie"))
            csrf = _scope_header(scope, CSRF_HEADER)
            if not self.credential.request_ok(cookie, csrf, self.clock()):
                response = JSONResponse({"error": REFUSED}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

    def _needs_user(self, scope: Scope) -> bool:
        if not self.require_user_pairing:
            return False
        classified = classify(self.routes(), scope)
        user_only = classified.policy is not None and (
            classified.policy.kind == Kind.USER_ONLY
        )
        return user_only and classified.route_key != PAIRING_ROUTE_KEY


def create_pairing_routes(
    credential: UserCredential,
    *,
    require_user_pairing: bool = True,
    clock: Callable[[], float] = time.time,
) -> list[Route]:
    async def status(request: Request) -> JSONResponse:
        cookie = request.cookies.get(COOKIE_NAME)
        csrf = credential.csrf_token(cookie, clock())
        return JSONResponse(
            {
                "enforced": require_user_pairing,
                "paired": csrf is not None,
                "csrf": csrf,
            }
        )

    async def pair(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except json.JSONDecodeError, UnicodeDecodeError:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        code = body.get("code") if isinstance(body, dict) else None
        if not isinstance(code, str) or len(code) > 64:
            return JSONResponse({"error": "code is required"}, status_code=400)
        cookie = credential.pair(code, clock())
        if cookie is None:
            return JSONResponse({"error": "pairing code refused"}, status_code=403)
        csrf = credential.csrf_token(cookie, clock())
        response = JSONResponse(
            {"enforced": require_user_pairing, "paired": True, "csrf": csrf}
        )
        response.set_cookie(
            COOKIE_NAME,
            cookie,
            max_age=COOKIE_TTL_SECONDS,
            httponly=True,
            secure=cookie_secure(request.url.scheme, request.headers),
            samesite="strict",
            path="/",
        )
        return response

    return [
        Route(PAIRING_PATH, status, methods=["GET"]),
        Route(PAIRING_PATH, pair, methods=["POST"]),
    ]
