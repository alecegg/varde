from __future__ import annotations

import asyncio

import pytest
from node_host_helpers import make_host
from varde_runner.node_host import CallTimeout, HostCallError, HostDown


def run(coro):
    return asyncio.run(coro)


def test_echo_burst_slow_and_ready_first() -> None:
    async def scenario() -> None:
        host = make_host()
        events = host.subscribe("s1")
        await host.start()
        try:
            assert host.state == "ready"
            assert await host.call("echo", {"a": [1, "é"]}) == {"a": [1, "é"]}
            slow = asyncio.create_task(host.call("slow", {"ms": 300}))
            fast = await host.call("echo", {"n": 1})
            assert fast == {"n": 1}
            assert not slow.done()
            assert await slow == {"slept": 300}
            assert await host.call("burst", {"n": 50, "session": "s1"}) == {
                "emitted": 50
            }
            seqs = [(await asyncio.wait_for(anext(events), 5)).seq for _ in range(50)]
            assert seqs == sorted(seqs)
            assert len(set(seqs)) == 50
        finally:
            await host.stop()
        assert host.state == "down"

    run(scenario())


def test_error_reply_timeout_and_bad_result() -> None:
    async def scenario() -> None:
        host = make_host()
        await host.start()
        try:
            with pytest.raises(HostCallError) as unknown:
                await host.call("nope")
            assert unknown.value.code == "unknown_method"
            with pytest.raises(HostCallError) as bad:
                await host.call("non-object")
            assert bad.value.code == "bad_result"
            with pytest.raises(CallTimeout):
                await host.call("hang", timeout_s=0.2)
            assert host.state == "ready"
            assert await host.call("echo", {"ok": True}) == {"ok": True}
        finally:
            await host.stop()

    run(scenario())


def test_engine_stdout_does_not_corrupt_frames() -> None:
    async def scenario() -> None:
        host = make_host()
        await host.start()
        try:
            assert await host.call("stdout-noise") == {}
            assert any("must not corrupt" in line for line in host.stderr_tail())
            assert await host.call("echo", {"x": 1}) == {"x": 1}
        finally:
            await host.stop()

    run(scenario())


def test_call_after_stop_raises_host_down() -> None:
    async def scenario() -> None:
        host = make_host()
        await host.start()
        await host.stop()
        with pytest.raises(HostDown):
            await host.call("echo")

    run(scenario())
