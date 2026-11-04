"""No-cursor long poll keeps events published while it waits; streams do not leak."""

import asyncio
import contextlib
import threading
import time
from pathlib import Path

from starlette.requests import Request
from starlette.routing import Route
from varde_serve.daemon.app import DaemonContext
from varde_serve.daemon.config import ServeConfig
from varde_serve.daemon.tokens import Tokens
from varde_serve.events.buffer import EventBuffer
from varde_serve.events.routes import event_routes, next_events


def test_no_cursor_wait_returns_an_event_published_during_the_wait() -> None:
    buffer = EventBuffer()
    threading.Timer(0.3, lambda: buffer.publish("doc.comment", "a.md", {})).start()
    started = time.monotonic()
    events, reset = asyncio.run(next_events(buffer, None, 10, 3))
    assert [e["kind"] for e in events] == ["doc.comment"]
    assert not reset
    assert time.monotonic() - started < 2.0


def test_no_cursor_without_events_times_out_empty() -> None:
    events, reset = asyncio.run(next_events(EventBuffer(), None, 10, 0.2))
    assert (events, reset) == ([], False)


def context(tmp_path: Path) -> DaemonContext:
    return DaemonContext(ServeConfig(), Tokens("h", "m"), "t", 1, static_dir=tmp_path)


def get(path: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1),
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": True}

    return Request(scope, receive)


def stream_route(ctx: DaemonContext) -> Route:
    found = [r for r in event_routes(ctx) if isinstance(r, Route)]
    return next(r for r in found if r.path == "/api/events")


def test_an_unstarted_stream_response_is_not_counted(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    stream = stream_route(ctx)
    for _ in range(40):  # cancelled before the body is ever iterated
        asyncio.run(stream.endpoint(get("/api/events")))
    assert ctx.open_streams == 0


def test_a_started_stream_is_counted_then_released(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    stream = stream_route(ctx)

    async def scenario() -> tuple[int, int]:
        response = await stream.endpoint(get("/api/events"))
        iterator = response.body_iterator
        first = asyncio.ensure_future(iterator.__anext__())
        await asyncio.sleep(0.2)
        during = ctx.open_streams
        first.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await first
        await iterator.aclose()
        return during, ctx.open_streams

    during, after = asyncio.run(scenario())
    assert (during, after) == (1, 0)
