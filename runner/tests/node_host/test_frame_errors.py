from __future__ import annotations

import asyncio
import contextlib

from node_host_helpers import await_until, make_host
from varde_runner.node_host import HostRestarted
from varde_runner.node_host.frames import MAX_LINE_BYTES


def test_malformed_host_line_is_skipped_and_reported() -> None:
    async def scenario() -> None:
        host = make_host()
        errors = host.subscribe(None)
        await host.start()
        try:
            await host.call("raw-line", {"line": "this is not json"})
            assert await host.call("echo", {"still": "working"}) == {"still": "working"}
            names = []
            while not any(name == "host_frame_error" for name in names):
                names.append((await asyncio.wait_for(anext(errors), 5)).event)
            assert host.state == "ready"
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_oversize_host_line_kills_host_and_restarts() -> None:
    async def scenario() -> None:
        host = make_host()
        await host.start()
        restarted = []
        host.on_restart(lambda: restarted.append(True))
        try:
            with contextlib.suppress(HostRestarted):
                await host.call("big", {"bytes": MAX_LINE_BYTES + 10}, timeout_s=30)
            assert await await_until(lambda: bool(restarted), 15)
            assert await host.call("echo", {"back": 1}) == {"back": 1}
        finally:
            await host.stop()

    asyncio.run(scenario())
