import asyncio
import multiprocessing
from pathlib import Path
from typing import Any

from varde_data.locking import file_lock, read_complete_lines


def _hold_lock_worker(path: str, acquired: Any, release: Any) -> None:
    with file_lock(Path(path), timeout=5):
        acquired.set()
        release.wait(5)


def test_lock_free_reader_does_not_stall_event_loop(tmp_path: Path) -> None:
    data_path = tmp_path / "events.jsonl"
    lock_path = tmp_path / ".events.lock"
    data_path.write_bytes(b"ready\n")

    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    release = context.Event()
    worker = context.Process(
        target=_hold_lock_worker,
        args=(str(lock_path), acquired, release),
    )
    worker.start()
    try:
        assert acquired.wait(5)

        async def read_while_ticking() -> None:
            ticks = 0
            ticked = asyncio.Event()

            async def ticker() -> None:
                nonlocal ticks
                while not ticked.is_set():
                    ticks += 1
                    await asyncio.sleep(0.001)

            ticker_task = asyncio.create_task(ticker())
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(read_complete_lines, data_path),
                    timeout=1,
                )
                await asyncio.sleep(0.01)
                assert result == [b"ready"]
                assert ticks > 0
            finally:
                ticked.set()
                await ticker_task

        asyncio.run(read_while_ticking())
    finally:
        release.set()
        worker.join(5)
        if worker.is_alive():
            worker.terminate()
            worker.join(5)
    assert worker.exitcode == 0
