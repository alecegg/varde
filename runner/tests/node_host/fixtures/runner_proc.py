"""Stand-in runner: starts a host, spawns children, prints their pids, then idles."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from varde_runner.node_host import NodeHost


async def main(host_script: str, engine: str, state_path: str) -> None:
    host = NodeHost(["node", host_script], engine, state_path=Path(state_path))
    await host.start()
    group_child = await host.call("spawn-child", {"tracked": False})
    tracked_child = await host.call("spawn-child", {"tracked": True})
    print(
        json.dumps(
            {
                "host": host.pid,
                "group_child": group_child["pid"],
                "tracked_child": tracked_child["pid"],
            }
        ),
        flush=True,
    )
    await asyncio.sleep(600)


asyncio.run(main(*sys.argv[1:4]))
