from __future__ import annotations

import asyncio
import fcntl
import threading
from contextlib import suppress
from pathlib import Path

from varde_runner.relay import DataRelay


def test_held_address_lock_does_not_block_event_loop(tmp_path: Path):
    lock = tmp_path / ".cache/inbox/addresses/mailman/.lock"
    lock.parent.mkdir(parents=True)
    ready = threading.Event()
    release = threading.Event()

    def hold_lock():
        with lock.open("a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            ready.set()
            release.wait(10)
            fcntl.flock(stream, fcntl.LOCK_UN)

    thread = threading.Thread(target=hold_lock)
    thread.start()
    assert ready.wait(5)

    async def exercise():
        adapter = DataRelay(tmp_path)
        operation = asyncio.create_task(adapter.issue_and_bind("runner-test"))
        await asyncio.sleep(0.05)
        tick = asyncio.get_running_loop().time()
        await asyncio.sleep(0.05)
        assert asyncio.get_running_loop().time() > tick
        assert not operation.done()
        release.set()
        await operation

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        thread.join(5)


def test_cancel_wait_leases_nothing(tmp_path: Path):
    async def exercise():
        adapter = DataRelay(tmp_path)
        token = await adapter.issue_and_bind("runner-wait")
        wait = asyncio.create_task(adapter.wait(token))
        await asyncio.sleep(0.05)
        wait.cancel()
        with suppress(asyncio.CancelledError):
            await wait
        snapshot = await asyncio.to_thread(adapter.addresses.relay_snapshot)
        assert not snapshot.leases
        await adapter.end(token)
        await adapter.unbind("runner-wait")

    asyncio.run(exercise())


def test_each_wait_uses_a_fresh_stop_event(tmp_path: Path):
    adapter = DataRelay(tmp_path)
    first_started = threading.Event()
    events = []

    def record_wait(identity, timeout, *, stop, poll=None):
        event = stop.__self__
        events.append(event)
        if len(events) == 1:
            first_started.set()
            while not stop():
                threading.Event().wait(0.005)
        return {"status": "none"}

    adapter.service.wait = record_wait  # type: ignore[assignment]

    async def exercise():
        first = asyncio.create_task(adapter.wait("token"))
        assert await asyncio.to_thread(first_started.wait, 3)
        first.cancel()
        with suppress(asyncio.CancelledError):
            await first
        assert events[0].is_set()

        await adapter.wait("token")

        assert events[1] is not events[0]
        assert events[0].is_set()

    asyncio.run(exercise())
