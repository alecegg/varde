from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

from starlette.requests import Request
from starlette.responses import StreamingResponse
from varde_runner.plugins import SessionSpec
from varde_runner.plugins.pi_rpc.plugin import PiRpcPlugin
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.supervisor import Supervisor
from varde_runner.web.agent_watch import create_agent_watch_route

FAKE = Path(__file__).parent / "fakes" / "fake_pi_rpc_delayed.py"


def test_delayed_batched_pi_turn_reaches_watch_snapshot(tmp_path, caplog):
    caplog.set_level("INFO")

    async def run():
        plugin = PiRpcPlugin(FAKE, state_dir=tmp_path / "state")
        registry = PluginRegistry(["pi_rpc"])
        registry.register("pi_rpc", plugin, provider_key="pi-rpc")
        supervisor = Supervisor(tmp_path / "runner", registry)
        await supervisor.start()
        try:
            ref = await supervisor.start_session(
                SessionSpec(
                    "pi-rpc",
                    "deepseek/deepseek-v4-flash",
                    "workspace",
                    str(tmp_path),
                    "Reply with READY",
                    reasoning_effort="high",
                    mode_id="read-only",
                ),
                "builder",
            )
            deadline = asyncio.get_running_loop().time() + 2
            while not supervisor.store.latest_events(ref.session_id, 200):
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError("supervisor did not persist buffered Pi events")
                await asyncio.sleep(0.01)

            async def get_supervisor():
                return supervisor

            route = create_agent_watch_route(get_supervisor)
            request = Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": f"/api/agents/{ref.session_id}/watch",
                    "query_string": (
                        f"client=replay-{uuid.uuid4().hex}&role=writer".encode()
                    ),
                    "path_params": {"id": ref.session_id},
                    "headers": [],
                    "scheme": "http",
                    "server": ("127.0.0.1", 80),
                    "client": ("127.0.0.1", 12345),
                    "http_version": "1.1",
                }
            )
            response = await route.endpoint(request)
            assert isinstance(response, StreamingResponse)
            iterator = cast("AsyncGenerator[bytes]", response.body_iterator)
            body = await asyncio.wait_for(anext(iterator), 1)
            message = json.loads(body.decode().split("data: ", 1)[1])
            assert message["type"] == "snapshot"
            kinds = [event["kind"] for event in message["events"]]
            assert "text" in kinds
            assert "status" in kinds
            assert any(
                event["kind"] == "text" and event["payload"]["text"] == "READY"
                for event in message["events"]
            )
            assert "pi_rpc_start" in caplog.text
            assert "pi_rpc_first_stdout_frame" in caplog.text
            assert "disposition=started" in caplog.text
            assert "Reply with READY" not in caplog.text
            await iterator.aclose()
        finally:
            await supervisor.shutdown()
            await plugin.close()
            supervisor.store.close()

    asyncio.run(run())
