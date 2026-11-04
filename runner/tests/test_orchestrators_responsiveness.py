from __future__ import annotations

import asyncio
import threading
import time
from urllib.parse import urlsplit

from test_web import setup_app


def test_slow_plan_rows_do_not_block_orchestrators_event_loop(tmp_path, monkeypatch):
    import varde_runner.web.app as web_app

    app, _, store = setup_app(tmp_path, monkeypatch)
    started = threading.Event()
    release = threading.Event()
    ticks_at_plan_read: list[int] = []
    ticks_at_release: list[int] = []
    ticks = 0

    def slow_plan_rows(*_args, **_kwargs):
        started.set()
        ticks_at_plan_read.append(ticks)
        release.wait(timeout=2)
        return [], [], []

    monkeypatch.setattr(web_app, "_plan_rows", slow_plan_rows)

    async def request_and_tick() -> tuple[int, int]:
        parsed_path = urlsplit("/api/orchestrators")
        messages = []
        received = False
        done = asyncio.Event()

        async def receive():
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        async def tick():
            nonlocal ticks
            while not done.is_set():
                ticks += 1
                await asyncio.sleep(0.005)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "host": "localhost:8765",
            "path": parsed_path.path,
            "raw_path": parsed_path.path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"localhost:8765")],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 8765),
        }

        ticker = asyncio.create_task(tick())

        def release_plan_read():
            started.wait(timeout=2)
            time.sleep(0.1)
            ticks_at_release.append(ticks)
            release.set()

        releaser = threading.Thread(target=release_plan_read, daemon=True)
        releaser.start()
        try:
            await app(scope, receive, send)
        finally:
            done.set()
            release.set()
            await ticker
            releaser.join()
        status = next(
            item["status"] for item in messages if item["type"] == "http.response.start"
        )
        return status, ticks

    status, ticks = asyncio.run(request_and_tick())

    assert started.is_set()
    assert status == 200
    assert ticks_at_release[0] > ticks_at_plan_read[0]
    store.close()
