"""Pure request-gate rules: Host, Origin, route classes, scopes, tokens."""

from __future__ import annotations

import hmac
import re
import time
from collections import deque
from collections.abc import Callable
from enum import StrEnum


class RouteClass(StrEnum):
    PUBLIC = "public"
    READ = "read"
    AGENT_WRITE = "agent-write"
    HUMAN_WRITE = "human-write"


class Scope(StrEnum):
    HUMAN = "human"
    MCP = "mcp"


WRITE_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})
WriteRoute = tuple[frozenset[str], re.Pattern[str], RouteClass]
# Always present: stopping the daemon needs the human token.
BASE_WRITE_ROUTES: list[WriteRoute] = [
    (frozenset({"POST"}), re.compile(r"/shutdown"), RouteClass.HUMAN_WRITE),
]
# The class table is derived from the route definitions (see `api.routes`), in
# router order, so a class can never disagree with the handler that is reached.
WRITE_ROUTES: list[WriteRoute] = list(BASE_WRITE_ROUTES)
# Stopping the daemon is not an edit: it needs the human token, not allow_edit.
EDIT_EXEMPT = frozenset({"/shutdown"})
PUBLIC_PATHS = frozenset({"/health", "/login", "/auth/session"})
PUBLIC_PREFIXES = ("/static/",)


def set_write_routes(routes: list[WriteRoute]) -> None:
    """Replace the endpoint part of the table (the base routes stay)."""
    WRITE_ROUTES[:] = [*BASE_WRITE_ROUTES, *routes]


def route_class(method: str, path: str) -> RouteClass:
    """Class of a request; an unknown write is human-write (fail closed)."""
    if method in WRITE_METHODS:
        if path == "/auth/session":
            return RouteClass.PUBLIC
        for methods, pattern, found in WRITE_ROUTES:
            if method in methods and pattern.fullmatch(path):
                return found
        return RouteClass.HUMAN_WRITE
    if path == "/" or path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        return RouteClass.PUBLIC
    return RouteClass.READ


def write_denied(path: str, token_ok: bool, allow_edit: bool) -> str | None:
    """Return the error code that refuses a write to `path`, else None."""
    if route_class("POST", path) is RouteClass.PUBLIC:
        return None
    if not token_ok:
        return "unauthorized"
    if not allow_edit and path not in EDIT_EXEMPT:
        return "edit_disabled"
    return None


def scope_denied(klass: RouteClass, scope: Scope | None) -> bool:
    """The mcp scope may never reach a human-write route."""
    return klass is RouteClass.HUMAN_WRITE and scope is Scope.MCP


def token_scope(presented: str, human: str, mcp: str) -> Scope | None:
    if not presented:
        return None
    if hmac.compare_digest(presented.encode(), human.encode()):
        return Scope.HUMAN
    if hmac.compare_digest(presented.encode(), mcp.encode()):
        return Scope.MCP
    return None


def allowed_hosts(port: int, extra: tuple[str, ...]) -> frozenset[str]:
    names = (f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}")
    return frozenset({*names, *extra})


def host_ok(host_header: str | None, allowed: frozenset[str]) -> bool:
    return host_header is not None and host_header.lower() in allowed


def origin_ok(origin: str | None, allowed: frozenset[str]) -> bool:
    """No Origin passes; otherwise its host must be in the Host allowlist."""
    if origin is None:
        return True
    host = origin.split("://", 1)[-1].lower()
    return host in allowed


class FailureLimiter:
    """At most `limit` failures per `window_s`; then refuse."""

    def __init__(
        self,
        limit: int = 5,
        window_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window_s = window_s
        self._clock = clock
        self._failures: deque[float] = deque()

    def _trim(self) -> None:
        cutoff = self._clock() - self._window_s
        while self._failures and self._failures[0] <= cutoff:
            self._failures.popleft()

    def blocked(self) -> bool:
        self._trim()
        return len(self._failures) >= self._limit

    def record_failure(self) -> None:
        self._failures.append(self._clock())


class PerClientLimiter:
    """One `FailureLimiter` per client address, bounded in size."""

    def __init__(
        self,
        limit: int = 5,
        window_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        max_clients: int = 1024,
    ) -> None:
        self._new = lambda: FailureLimiter(limit, window_s, clock)
        self._max_clients = max_clients
        self._by_client: dict[str, FailureLimiter] = {}

    def blocked(self, client: str) -> bool:
        limiter = self._by_client.get(client)
        return limiter is not None and limiter.blocked()

    def record_failure(self, client: str) -> None:
        if client not in self._by_client:
            if len(self._by_client) >= self._max_clients:
                self._by_client.pop(next(iter(self._by_client)))
            self._by_client[client] = self._new()
        self._by_client[client].record_failure()
