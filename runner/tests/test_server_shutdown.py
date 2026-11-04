from __future__ import annotations

import socket
import threading
import time

import uvicorn
from stop_server import stop_server
from varde_runner import GRACEFUL_SHUTDOWN_TIMEOUT
from varde_runner.web import create_app


def test_server_shutdown_bounds_open_events_stream(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    server = uvicorn.Server(
        uvicorn.Config(
            create_app(
                data_dir=tmp_path,
                bound_port=port,
                allowed_hosts=frozenset({"127.0.0.1"}),
            ),
            host="127.0.0.1",
            port=port,
            log_level="error",
            lifespan="off",
            timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started

        with socket.create_connection(("127.0.0.1", port), timeout=15) as client:
            client.settimeout(15)
            client.sendall(b"GET /events HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            response = client.recv(4096)
            assert b"200 OK" in response
    finally:
        stop_server(server, thread)
