"""Closed route policy for the manager bot (fail closed).

Every route of the app is keyed by (method, route path template) and is `read`,
`bot_writer`, `allow(constraint)` or `user_only`. A route that is not in the table
is denied. `HEAD` is classified as `GET`.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from starlette.routing import BaseRoute, Match, Mount, Route


class Kind(StrEnum):
    READ = "read"
    BOT_WRITER = "bot_writer"
    ALLOW = "allow"
    USER_ONLY = "user_only"
    USER_DATA = "user_data"


@dataclass(frozen=True, slots=True)
class Policy:
    kind: Kind
    constraint: str | None = None


READ = Policy(Kind.READ)
USER_ONLY = Policy(Kind.USER_ONLY)
USER_DATA = Policy(Kind.USER_DATA)


def allow(constraint: str) -> Policy:
    return Policy(Kind.ALLOW, constraint)


_GET_READ = (
    "/",
    "/agents",
    "/agents/profile/{identity_id:str}",
    "/api/agents",
    "/api/agents/capabilities",
    "/api/agents/{id:str}/watch",
    "/api/bot/audit",
    "/api/bot/state",
    "/api/decision-metrics",
    "/api/degraded",
    "/api/identities",
    "/api/identities/{identity_id:str}/instances",
    "/api/plans/{plan_id:path}/merge-approval",
    "/api/needs-you-count",
    "/api/plans",
    "/api/plans/{plan_id:str}",
    "/api/plans/{plan_id:str}/task-queue",
    "/api/queue",
    "/api/queue/roles",
    "/api/queue/roles/{role:str}",
    "/api/home",
    "/api/roles/models",
    "/api/runner/status",
    "/apple-touch-icon.png",
    "/chat",
    "/chat/needs",
    "/chats",
    "/favicon-16.png",
    "/favicon-32.png",
    "/favicon.ico",
    "/favicon.svg",
    "/icon-192.png",
    "/icon-512.png",
    "/icons/dark/{asset:str}",
    "/home",
    "/jobs",
    "/manifest.webmanifest",
    "/new-item",
    "/plans",
    "/plans/{plan_id:str}",
    "/queue",
    "/queue/{role:str}",
    "/roles",
    "/settings",
    "/settings/{section:str}",
    "/thread/{agent_id:str}",
    "/threads/{thread_id:str}",
    "/_app",
    "/static",
)

_USER_ONLY_READS = ("/mailbox", "/threads")

# Session, chat, event and mail data the bot must not read; the user is not gated.
_GET_USER_DATA = (
    "/profile/{agent_id:str}",
    "/api/workspaces",
    "/api/pairing",
    "/api/learn/sweep",
    "/api/work-items/{item_id:str}",
    "/api/work-items",
    "/api/chat",
    "/api/chat/stream",
    "/api/guard/approvals",
    "/api/guard/verdicts",
    "/api/instance-threads",
    "/api/jobs",
    "/api/jobs/{key:str}/runs",
    "/api/mail-soak",
    "/api/mailbox",
    "/api/mailbox/{decision_id:str}",
    "/api/mailbox/{decision_id:str}/evidence/{index:str}",
    "/api/orchestrators",
    "/api/pins",
    "/api/relay",
    "/api/runner/config",
    "/api/runner/config/toml",
    "/api/settings",
    "/api/threads",
    "/events",
)

_USER_ONLY_WRITES = (
    ("DELETE", "/api/instance-threads/{agent_id:str}/takeover"),
    ("DELETE", "/api/workspaces"),
    ("POST", "/api/agents/{id:str}/mode"),
    ("POST", "/api/agents/{id:str}/respond"),
    ("POST", "/api/settings"),
    ("POST", "/api/bot/control"),
    ("POST", "/api/agents/{id:str}/{action:str}"),
    ("POST", "/api/chat/messages"),
    ("POST", "/api/guard/revoke"),
    ("POST", "/api/guard/unrevoke"),
    ("POST", "/api/instance-threads/{agent_id:str}/takeover"),
    ("POST", "/api/instance-threads/{agent_id:str}/takeover/heartbeat"),
    ("POST", "/api/jobs/{key:str}/{action:str}"),
    ("POST", "/api/learn/sweep/run"),
    ("POST", "/api/mailbox/{decision_id:str}/answer"),
    ("POST", "/api/plans/{plan_id:path}/merge-approval"),
    ("POST", "/api/plans/{plan_id:str}/comments/{comment_id:str}"),
    ("POST", "/api/mailbox/{decision_id:str}/dismiss"),
    ("POST", "/api/mailbox/{decision_id:str}/restore"),
    ("POST", "/api/orchestrators/{address:str}/status"),
    ("POST", "/api/pairing"),
    ("POST", "/api/probe"),
    ("POST", "/api/work-items/{item_id:str}/decision"),
    ("POST", "/api/work-items/{item_id:str}/plan-ready"),
    ("POST", "/api/work-items/{item_id:str}/questions/{decision_id:str}/answer"),
    ("POST", "/api/workspaces"),
    ("POST", "/entries/{key:str}/retry"),
    ("POST", "/mailbox/{decision_id:str}/answer"),
    ("POST", "/new-item"),
    ("POST", "/new-item/{item_id:str}/decision"),
    ("POST", "/new-item/{item_id:str}/plan-ready"),
    ("POST", "/new-item/{item_id:str}/questions/{decision_id:str}/answer"),
    ("POST", "/roles"),
    ("PUT", "/api/identities/{identity_id:str}"),
    ("PUT", "/api/pins"),
    ("PUT", "/api/jobs/{key:str}/budget"),
    ("PUT", "/api/runner/config"),
    ("POST", "/api/runner/config/sdk-flip/preview"),
    ("POST", "/api/runner/config/sdk-flip/apply"),
    ("POST", "/api/runner/restart"),
)

_ALLOWED_WRITES: tuple[tuple[str, str, str], ...] = (
    ("POST", "/api/agents", "launch"),
    ("POST", "/api/agents/{id:str}/prompt", "agent_action"),
    ("POST", "/api/agents/{id:str}/interrupt", "agent_action"),
    ("POST", "/api/agents/{id:str}/resume", "agent_action"),
    ("POST", "/api/agents/{id:str}/stop", "agent_action"),
    ("POST", "/api/agents/{id:str}/archive", "agent_action"),
    ("POST", "/api/work-items", "stub"),
    ("POST", "/api/queue/move", "queue_move"),
    ("POST", "/api/plans/{plan_id:str}/comments", "plan_comment"),
    ("POST", "/api/bot/say", "bot_say"),
    ("POST", "/api/bot/notes", "bot_notes"),
    ("POST", "/api/bot/mailbox", "bot_mailbox"),
    ("PUT", "/api/plans/{plan_id:str}/body", "plan_edit"),
)

POLICY: dict[tuple[str, str], Policy] = {
    **{("GET", path): READ for path in _GET_READ},
    **{("GET", path): USER_DATA for path in _GET_USER_DATA},
    **{("GET", path): USER_ONLY for path in _USER_ONLY_READS},
    **dict.fromkeys(_USER_ONLY_WRITES, USER_ONLY),
    ("POST", "/api/plans/{plan_id:path}/merge-approval/agent"): USER_DATA,
    ("GET", "/approve"): USER_ONLY,
    **{(method, path): allow(name) for method, path, name in _ALLOWED_WRITES},
}


def policy_for(method: str, route_path: str) -> Policy | None:
    method = "GET" if method == "HEAD" else method
    return POLICY.get((method, route_path))


def match_route(
    routes: Sequence[BaseRoute], scope: Mapping[str, Any], prefix: str = ""
) -> tuple[BaseRoute, str] | None:
    """First full match and its full path template, mount prefixes included.

    A route's own ``path`` is relative to its mounts, so the table is keyed by the
    full template: a mounted ``/api/agents`` is ``/extension/api/agents`` and
    inherits nothing from the top-level route of the same child path.
    """
    for route in routes:
        match, child = route.matches(dict(scope))  # type: ignore[arg-type]
        if match != Match.FULL:
            continue
        template = prefix + getattr(route, "path", "")
        inner = getattr(getattr(route, "app", None), "routes", None)
        if isinstance(route, Mount) and inner:
            nested = match_route(inner, {**scope, **child}, template)
            return nested or (route, template)
        return route, template
    return None


@dataclass(frozen=True, slots=True)
class Classified:
    """What the policy says about one request."""

    route_key: str  # "METHOD path-template", for the audit log
    policy: Policy | None
    params: Mapping[str, Any]


def classify(routes: Sequence[BaseRoute], scope: Mapping[str, Any]) -> Classified:
    """Classify a request; an unmatched or unlisted route has no policy."""
    method = scope["method"]
    matched = match_route(routes, scope)
    if matched is None:
        return Classified(f"{method} (unmatched)", None, {})
    route, template = matched
    _, child = route.matches(dict(scope))  # type: ignore[arg-type]
    return Classified(
        f"{method} {template}",
        policy_for(method, template),
        child.get("path_params", {}),
    )


def iter_route_keys(
    routes: Sequence[BaseRoute], prefix: str = ""
) -> Iterator[tuple[str, str]]:
    """Every (method, full path template) the app serves, mounted routers included."""
    for route in routes:
        template = prefix + getattr(route, "path", "")
        if isinstance(route, Route):
            for method in sorted(route.methods or ()):
                if method != "HEAD":
                    yield method, template
        elif isinstance(route, Mount):
            inner = getattr(route.app, "routes", None)
            if inner:
                yield from iter_route_keys(inner, template)
            else:
                yield "GET", template


def unclassified_routes(routes: Sequence[BaseRoute]) -> list[tuple[str, str]]:
    """Routes the app serves that the policy table does not list (must be empty)."""
    return [key for key in iter_route_keys(routes) if key not in POLICY]
