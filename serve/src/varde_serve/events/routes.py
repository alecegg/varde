"""HTTP surface of the event buffer: SSE stream and cursor poll."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import BaseRoute, Route

from varde_serve.events.buffer import EventBuffer

if TYPE_CHECKING:
    from varde_serve.daemon.app import DaemonContext

MAX_WAIT_S = 25
MAX_LIMIT = 100
TICK_S = 0.1


def sse_frame(event: dict[str, Any]) -> str:
    return f"id: {event['id']}\nevent: {event['kind']}\ndata: {json.dumps(event)}\n\n"


def _int(value: str | None, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value))) if value is not None else default
    except ValueError:
        return default


async def next_events(
    buffer: EventBuffer, cursor: str | None, limit: int, wait_s: float
) -> tuple[list[dict[str, Any]], bool]:
    """Events after `cursor`; wait up to `wait_s` for the first one.

    No cursor means "from now": it is resolved once, before waiting, so an
    event published during the wait is returned, not skipped.
    """
    cursor = cursor or buffer.cursor
    deadline = time.monotonic() + wait_s
    while True:
        events, reset = buffer.since(cursor, limit)
        if events or reset or time.monotonic() >= deadline:
            return events, reset
        await asyncio.sleep(TICK_S)


def event_routes(ctx: DaemonContext) -> list[BaseRoute]:
    from varde_serve.daemon.app import MAX_STREAMS, refuse

    async def poll(request: Request) -> Response:
        query = request.query_params
        wait = _int(query.get("wait_s"), 0, 0, MAX_WAIT_S)
        limit = _int(query.get("limit"), MAX_LIMIT, 1, MAX_LIMIT)
        start = query.get("cursor") or ctx.events.cursor
        events, reset = await next_events(ctx.events, start, limit, wait)
        resume = ctx.events.cursor if reset else start
        newest = events[-1]["id"] if events else resume
        body: dict[str, Any] = {"events": events, "cursor": newest}
        if reset:
            body["reset"] = True
        return JSONResponse(body)

    async def stream(request: Request) -> Response:
        if ctx.open_streams >= MAX_STREAMS:
            return refuse("too_many_streams")
        cursor = request.headers.get("last-event-id") or request.query_params.get(
            "cursor"
        )
        return StreamingResponse(
            frames(request, cursor),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store"},
        )

    async def frames(request: Request, cursor: str | None) -> AsyncIterator[str]:
        # Counted inside the generator: a response cancelled before iteration
        # starts never runs the `finally`, so it must not have been counted.
        ctx.open_streams += 1
        try:
            events, reset = ctx.events.since(cursor)
            last = cursor if cursor is not None else ctx.events.cursor
            if reset:
                yield sse_frame(ctx.events.reset_frame())
                last = ctx.events.cursor
            for event in events:
                yield sse_frame(event)
                last = event["id"]
            idle_since = time.monotonic()
            while not await request.is_disconnected():
                fresh, _ = ctx.events.since(last)
                for event in fresh:
                    yield sse_frame(event)
                    last = event["id"]
                    idle_since = time.monotonic()
                if time.monotonic() - idle_since >= ctx.keepalive_s:
                    yield ": keepalive\n\n"
                    idle_since = time.monotonic()
                await asyncio.sleep(TICK_S)
        finally:
            ctx.open_streams -= 1

    return [Route("/api/events", stream), Route("/api/events/poll", poll)]
