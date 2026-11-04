import sys
import threading
import traceback

import pytest
import uvicorn
from varde_runner import GRACEFUL_SHUTDOWN_TIMEOUT

SERVER_SHUTDOWN_TIMEOUT = GRACEFUL_SHUTDOWN_TIMEOUT + 5


def stop_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=SERVER_SHUTDOWN_TIMEOUT)
    if thread.is_alive():
        frames = sys._current_frames()
        stacks = "\n".join(
            f"\n--- {candidate.name} ---\n"
            f"{''.join(traceback.format_stack(frames[candidate.ident]))}"
            for candidate in threading.enumerate()
            if candidate.ident in frames
        )
        pytest.fail(
            f"uvicorn server thread {thread.name} did not stop within "
            f"{SERVER_SHUTDOWN_TIMEOUT}s; thread stacks:{stacks}",
            pytrace=False,
        )
