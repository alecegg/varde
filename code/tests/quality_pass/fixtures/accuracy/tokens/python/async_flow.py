"""Async and context management shapes for the token audit fixture set."""

import asyncio
from contextlib import asynccontextmanager

RATE = 0.25
LABELS = {"fast": 1, "slow": 8}


@asynccontextmanager
async def session(host: str, port: int = 8080):
    connection = {"host": host, "port": port}
    try:
        yield connection
    finally:
        connection.clear()


async def fetch_all(hosts: list[str]) -> list[bytes]:
    results = []
    async with session(hosts[0]) as connection:
        for host in hosts[1:]:
            data = await read(connection, host)
            results.append(data)
    await asyncio.sleep(RATE)
    return results


async def read(connection: dict, host: str) -> bytes:
    # The transport is a stub in this fixture; ordering still matters.
    return f"{connection['host']}:{host}".encode("utf-8")
