"""ASGI helpers for the manager-bot gateway tests."""

from __future__ import annotations

import json
from typing import Any


async def call(
    app,
    method: str,
    path: str,
    payload: Any = None,
    headers: dict[str, str] | None = None,
    query: str = "",
) -> tuple[int, Any]:
    body = json.dumps(payload).encode() if payload is not None else b""
    messages: list[dict] = []
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    merged = {"host": "127.0.0.1", **{k.lower(): v for k, v in (headers or {}).items()}}
    raw_headers = [(key.encode(), value.encode()) for key, value in merged.items()]
    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "root_path": "",
            "headers": raw_headers,
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 80),
        },
        receive,
        send,
    )
    status = messages[0]["status"]
    text = b"".join(item.get("body", b"") for item in messages[1:])
    return status, (json.loads(text) if text else None)
