from __future__ import annotations

import asyncio
import multiprocessing
from pathlib import Path
from typing import Any

from varde_data.config import DataConfig
from varde_data.locking import file_lock
from varde_data.open import open_data
from varde_data.records.messages import NewMessage


def _hold_lock(path: str, ready: Any, release: Any) -> None:
    with file_lock(Path(path), timeout=5):
        ready.set()
        release.wait(5)


def test_message_reads_do_not_wait_for_writer_lock_or_block_loop(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / ".cache" / "inbox"
    lock_path = inbox / ".messages.lock"
    repository = open_data(tmp_path, DataConfig()).messages
    repository.append(NewMessage("main", "main", "info", "populated"))
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    process = context.Process(target=_hold_lock, args=(str(lock_path), ready, release))
    process.start()
    try:
        assert ready.wait(5)

        async def check() -> None:
            read = asyncio.create_task(
                asyncio.to_thread(repository.peek_unread, "main")
            )
            loop_responsive = asyncio.Event()
            asyncio.get_running_loop().call_soon(loop_responsive.set)
            await asyncio.sleep(0)
            assert loop_responsive.is_set()
            rows = await asyncio.wait_for(read, timeout=1)
            assert [row.text for row in rows] == ["populated"]

        asyncio.run(check())
    finally:
        release.set()
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join()
        assert process.exitcode == 0
