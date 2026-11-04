"""The four tools and their mapping to daemon routes. Pure data and functions."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

WRITE_ACTIONS = ("comment", "reply", "mail_send", "friction_add")
DOMAINS = ["plans", "friction", "docs", "mail"]

TOOLS: list[dict[str, Any]] = [
    {
        "name": "varde_read",
        "description": "Read Varde state: plans, queue, friction, docs, mail.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "resource": {
                    "type": "string",
                    "description": "plans | plans/<id> | plans/<id>/tasks/<t> | queue "
                    "| friction | docs | docs/<path> | mail",
                },
                "query": {"type": "object", "description": "filters (friction)"},
                "limit": {"type": "integer", "maximum": 200},
            },
            "required": ["resource"],
        },
    },
    {
        "name": "varde_search",
        "description": "Search plans, friction, docs and mail.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "domain": {"enum": DOMAINS},
                "limit": {"type": "integer", "maximum": 50},
            },
            "required": ["q"],
        },
    },
    {
        "name": "varde_write",
        "description": "Comment, reply, send mail or add friction (needs allow_edit).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"enum": list(WRITE_ACTIONS)},
                "args": {
                    "type": "object",
                    "description": "comment {path, anchor, text}; reply {path, "
                    "comment_id, text}; mail_send {to, kind, text}; "
                    "friction_add {text, tags?}",
                },
            },
            "required": ["action", "args"],
        },
    },
    {
        "name": "varde_events",
        "description": "Poll change events; pass the returned cursor next time.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cursor": {"type": "string"},
                "limit": {"type": "integer", "maximum": 100},
                "wait_s": {"type": "integer", "minimum": 0, "maximum": 25},
            },
        },
    },
]
TOOL_NAMES = frozenset(tool["name"] for tool in TOOLS)
Route = tuple[str, str, dict[str, Any] | None]  # method, path+query, body


class BadArguments(ValueError):
    """The tool arguments do not fit the tool."""


def _text(args: dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value:
        raise BadArguments(f"{name} must be a non-empty string")
    return value


def _path(*parts: str) -> str:
    return "/".join(quote(part, safe="") for part in parts)


def _query(values: dict[str, Any]) -> str:
    kept = {k: v for k, v in values.items() if v is not None}
    return f"?{urlencode(kept)}" if kept else ""


def read_route(args: dict[str, Any]) -> Route:
    resource = _text(args, "resource").strip("/")
    parts = resource.split("/")
    raw_filters = args.get("query")
    filters: dict[str, Any] = raw_filters if isinstance(raw_filters, dict) else {}
    limit = args.get("limit")
    head = parts[0]
    if head == "plans" and len(parts) == 1:
        return "GET", "/api/plans", None
    if head == "plans" and len(parts) == 2:
        return "GET", f"/api/plans/{_path(parts[1])}", None
    if head == "plans" and len(parts) == 4 and parts[2] == "tasks":
        return "GET", f"/api/plans/{_path(parts[1])}/tasks/{_path(parts[3])}", None
    if head == "friction" and len(parts) == 1:
        merged = {
            "limit": limit,
            **{k: filters[k] for k in ("status", "tag") if k in filters},
        }
        return "GET", f"/api/friction{_query(merged)}", None
    if head in {"queue", "mail", "docs"} and len(parts) == 1:
        return "GET", f"/api/{head}", None
    if head == "docs":
        return (
            "GET",
            f"/api/docs/{'/'.join(quote(p, safe='') for p in parts[1:])}",
            None,
        )
    raise BadArguments(f"unknown resource {resource!r}")


def search_route(args: dict[str, Any]) -> Route:
    values = {
        "q": _text(args, "q"),
        "domain": args.get("domain"),
        "limit": args.get("limit"),
    }
    return "GET", f"/api/search{_query(values)}", None


def write_route(args: dict[str, Any]) -> Route:
    action, body = args.get("action"), args.get("args")
    if action not in WRITE_ACTIONS or not isinstance(body, dict):
        raise BadArguments(
            f"action must be one of {list(WRITE_ACTIONS)} with an args object"
        )
    if action == "comment":
        path = "/".join(quote(p, safe="") for p in _text(body, "path").split("/"))
        fields = {"anchor": _text(body, "anchor"), "text": _text(body, "text")}
        return "POST", f"/api/docs/{path}/comments", fields
    if action == "reply":
        path = "/".join(quote(p, safe="") for p in _text(body, "path").split("/"))
        cid = quote(_text(body, "comment_id"), safe="")
        return (
            "POST",
            f"/api/docs/{path}/comments/{cid}/replies",
            {"text": _text(body, "text")},
        )
    if action == "mail_send":
        fields = {name: _text(body, name) for name in ("to", "kind", "text")}
        return "POST", "/api/mail", fields
    tags = body.get("tags", [])
    return "POST", "/api/friction", {"text": _text(body, "text"), "tags": tags}


def events_route(args: dict[str, Any]) -> Route:
    values = {k: args.get(k) for k in ("cursor", "limit", "wait_s")}
    return "GET", f"/api/events/poll{_query(values)}", None


ROUTES = {
    "varde_read": read_route,
    "varde_search": search_route,
    "varde_write": write_route,
    "varde_events": events_route,
}


def route_for(tool: str, args: dict[str, Any]) -> Route:
    """Map a tool call to a daemon request; raise BadArguments."""
    if tool not in ROUTES:
        raise BadArguments(f"unknown tool {tool!r}")
    return ROUTES[tool](args)
