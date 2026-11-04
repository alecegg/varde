"""Small JSON-lines Unix socket transport for dashboard clients."""

from __future__ import annotations

import asyncio
import json
import os
import socket
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any


def create_server_socket(path: Path) -> socket.socket:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    previous_mask = os.umask(0o177)
    try:
        server.bind(str(path))
    except BaseException:
        server.close()
        raise
    finally:
        os.umask(previous_mask)
    os.chmod(path, 0o600)
    server.listen()
    server.setblocking(False)
    return server


async def serve_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
) -> None:
    try:
        while line := await reader.readline():
            try:
                response = await handler(json.loads(line))
            except Exception as exc:  # noqa: BLE001 - return plugin errors to IPC clients
                response = {"error": str(exc)}
            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()
