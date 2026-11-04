from __future__ import annotations

import asyncio
import stat

import pytest
from node_host_helpers import ECHO_ENGINE
from varde_runner.node_host import NodeHost, NodeHostError


def test_missing_node_fails_with_clear_error() -> None:
    async def scenario() -> None:
        host = NodeHost(["no-such-node-binary-xyz", "host.mjs"], ECHO_ENGINE)
        with pytest.raises(NodeHostError, match="no-such-node-binary-xyz"):
            await host.start()
        assert host.state == "down"

    asyncio.run(scenario())


def test_old_node_in_ready_frame_is_rejected(tmp_path) -> None:
    stub = tmp_path / "old-node"
    stub.write_text(
        "#!/bin/sh\n"
        'echo \'{"type":"ready","protocol":1,"engine":"x","node":"20.11.0"}\'\n'
        "sleep 30\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)

    async def scenario() -> None:
        host = NodeHost([str(stub)], ECHO_ENGINE, stop_grace_s=2.0)
        with pytest.raises(NodeHostError, match="older than 22.19"):
            await host.start()
        assert host.state == "down"

    asyncio.run(scenario())
