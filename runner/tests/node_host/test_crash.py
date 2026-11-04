from __future__ import annotations

import asyncio
import os
import signal

import pytest
from node_host_helpers import await_until, make_host
from varde_runner.node_host import HostCallError, HostDown, HostRestarted, NodeHostError

pytestmark = pytest.mark.slow


async def await_new_child(host, old_pid: int) -> bool:
    return await await_until(
        lambda: host.state == "ready" and host.pid not in (None, old_pid), 15
    )


def test_kill_9_fails_pending_restarts_and_runs_callbacks() -> None:
    async def scenario() -> None:
        host = make_host()
        calls = []
        host.on_restart(lambda: calls.append("sync"))

        async def later() -> None:
            calls.append("async")

        host.on_restart(later)
        await host.start()
        try:
            first_pid = host.pid
            assert first_pid is not None
            pending = asyncio.create_task(host.call("slow", {"ms": 30000}))
            await asyncio.sleep(0.2)
            os.kill(first_pid, signal.SIGKILL)
            with pytest.raises(HostRestarted):
                await pending
            assert await await_until(lambda: calls == ["sync", "async"], 15)
            assert host.state == "ready"
            assert host.pid != first_pid
            assert await host.call("echo", {"alive": 1}) == {"alive": 1}
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_fourth_death_in_window_leaves_down_with_diagnostic() -> None:
    async def scenario() -> None:
        host = make_host()
        events = host.subscribe(None)
        await host.start()
        try:
            old = host.pid
            assert old is not None
            os.kill(old, signal.SIGKILL)  # death 1
            for _ in range(2):  # deaths 2 and 3, each after a restart
                assert await await_new_child(host, old)
                old = host.pid
                assert old is not None
                with pytest.raises((HostRestarted, HostCallError)):
                    await host.call("crash", timeout_s=10)
            assert await await_new_child(host, old)
            with pytest.raises(HostRestarted):
                await host.call("crash", timeout_s=10)  # death 4
            assert await await_until(lambda: host.state == "down", 15)
            with pytest.raises(HostDown):
                await host.call("echo")
            assert "host deaths" in host.down_reason
            seen = []
            while "host_down" not in seen:
                seen.append((await asyncio.wait_for(anext(events), 5)).event)
            await host.restart()  # explicit restart resets the history
            assert host.state == "ready"
            assert await host.call("echo", {"x": 1}) == {"x": 1}
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_start_failure_raises_and_stays_down(tmp_path) -> None:
    async def scenario() -> None:
        host = make_host()
        host._engine_path = str(tmp_path / "missing-engine.mjs")
        with pytest.raises(NodeHostError, match="engine failed to start"):
            await host.start()
        assert host.state == "down"

    asyncio.run(scenario())


def test_unwritable_record_stops_host_and_allows_retry(tmp_path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")

    async def scenario() -> None:
        host = make_host(state_path=blocker / "host.json")
        with pytest.raises(NodeHostError, match="cannot (read|persist) host record"):
            await host.start()
        assert host.state == "down"
        assert host.pid is None
        host._state_path = tmp_path / "ok" / "host.json"
        await host.start()
        try:
            assert await host.call("echo", {"a": 1}) == {"a": 1}
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_record_write_failure_after_spawn_terminates_host(tmp_path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)

    async def scenario() -> None:
        host = make_host(state_path=locked / "sub" / "host.json")
        try:
            with pytest.raises(NodeHostError, match="cannot persist host record"):
                await host.start()
            assert host.state == "down"
            assert host.pid is None
        finally:
            locked.chmod(0o700)

    asyncio.run(scenario())
