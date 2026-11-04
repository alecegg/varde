"""SIGTERM cleanup, a spoofed /health, proxies and the discovery race."""

import http.server
import json
import os
import select
import signal
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest
from test_daemon import config_dir, request, spawner  # noqa: F401 - fixture
from varde_serve.daemon import lifecycle
from varde_serve.daemon.lifecycle import (
    DaemonError,
    ensure_daemon,
    genuine_health,
    probe_health,
)
from varde_serve.daemon.state import DaemonInfo, info_path, read_info, write_info
from varde_serve.daemon.tokens import state_dir

GOOD = {"version": "t", "api_version": 1, "features": [], "pid": 0}


def wait_until(check, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return False


def test_sigterm_removes_daemon_json(config_dir: Path) -> None:  # noqa: F811
    info = ensure_daemon(config_dir, spawner(config_dir))
    assert read_info(state_dir(config_dir)) is not None
    os.kill(info.pid, signal.SIGTERM)
    assert wait_until(lambda: not info_path(state_dir(config_dir)).exists(), 2.0)


def test_sigint_removes_daemon_json(config_dir: Path) -> None:  # noqa: F811
    info = ensure_daemon(config_dir, spawner(config_dir))
    os.kill(info.pid, signal.SIGINT)
    assert wait_until(lambda: not info_path(state_dir(config_dir)).exists(), 2.0)


class Impostor(http.server.BaseHTTPRequestHandler):
    body: ClassVar[dict] = GOOD
    seen_auth: ClassVar[list[str | None]] = []

    def do_GET(self) -> None:
        type(self).seen_auth.append(self.headers.get("Authorization"))
        data = json.dumps(type(self).body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def impostor() -> Iterator[tuple[type[Impostor], int]]:
    Impostor.seen_auth = []
    server = http.server.HTTPServer(("127.0.0.1", 0), Impostor)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield Impostor, server.server_address[1]
    server.shutdown()


@pytest.mark.parametrize("pid", [-1, 0, 1, True, "7", None, 1.5])
def test_probe_rejects_a_health_pid_that_is_not_a_positive_int(
    impostor: tuple[type[Impostor], int], pid: object
) -> None:
    handler, port = impostor
    handler.body = {**GOOD, "pid": pid}
    info = DaemonInfo(os.getpid(), port, "now", "t")
    assert probe_health(info) is None


def test_probe_rejects_a_pid_that_differs_from_daemon_json(
    impostor: tuple[type[Impostor], int],
) -> None:
    handler, port = impostor
    handler.body = {**GOOD, "pid": os.getpid() + 1}
    assert probe_health(DaemonInfo(os.getpid(), port, "now", "t")) is None


def test_probe_rejects_a_wrong_shape(impostor: tuple[type[Impostor], int]) -> None:
    handler, port = impostor
    handler.body = {"pid": os.getpid()}
    assert probe_health(DaemonInfo(os.getpid(), port, "now", "t")) is None


def test_genuine_health_requires_a_varde_serve_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = DaemonInfo(os.getpid(), 1, "now", "t")
    health = {**GOOD, "pid": os.getpid()}
    monkeypatch.setattr(lifecycle, "process_command", lambda pid: "python -m pytest")
    assert not genuine_health(health, info)
    monkeypatch.setattr(
        lifecycle, "process_command", lambda pid: "x -m varde_serve daemon"
    )
    assert genuine_health(health, info)
    monkeypatch.setattr(lifecycle, "process_command", lambda pid: None)  # ps unusable
    assert genuine_health(health, info)


def test_a_dead_pid_is_not_genuine() -> None:
    gone = DaemonInfo(2**22 + 12345, 1, "now", "t")
    assert not genuine_health({**GOOD, "pid": gone.pid}, gone)


def test_the_token_never_reaches_an_unverified_responder(
    config_dir: Path,  # noqa: F811
    impostor: tuple[type[Impostor], int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler, port = impostor
    handler.body = {**GOOD, "pid": os.getpid()}
    monkeypatch.setattr(lifecycle, "process_command", lambda pid: "python -m pytest")
    monkeypatch.setattr(lifecycle, "DISCOVERY_WAIT_S", 0.3)
    write_info(state_dir(config_dir), DaemonInfo(os.getpid(), port, "now", "t"))
    try:
        with pytest.raises(DaemonError):
            ensure_daemon(config_dir, lambda: None)
    finally:  # the fixture would SIGKILL the pid named here: this process
        info_path(state_dir(config_dir)).unlink()
    assert all(auth is None for auth in handler.seen_auth)


def test_proxy_environment_is_ignored_for_loopback(
    config_dir: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = ensure_daemon(config_dir, spawner(config_dir))
    proxy = socket.socket()
    proxy.bind(("127.0.0.1", 0))
    proxy.listen()
    url = f"http://127.0.0.1:{proxy.getsockname()[1]}"
    for name in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, url)
    monkeypatch.setenv("NO_PROXY", "")
    try:
        assert probe_health(info) is not None
        assert not select.select([proxy], [], [], 0.1)[0], "a request reached the proxy"
    finally:
        proxy.close()


def test_clients_never_delete_a_daemon_json_they_did_not_write(
    config_dir: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shim B finding the lock free must not erase a file D1 may have just written."""
    state = state_dir(config_dir)
    write_info(state, DaemonInfo(2**22 + 999, 1, "stale", "t"))
    before = info_path(state).read_bytes()
    monkeypatch.setattr(lifecycle, "DISCOVERY_WAIT_S", 0.2)
    spawned = []
    with pytest.raises(DaemonError):
        ensure_daemon(config_dir, lambda: spawned.append(1))
    assert spawned == [1]
    assert info_path(state).read_bytes() == before


def test_a_daemon_overwrites_a_stale_daemon_json(config_dir: Path) -> None:  # noqa: F811
    write_info(state_dir(config_dir), DaemonInfo(2**22 + 999, 1, "stale", "t"))
    info = ensure_daemon(config_dir, spawner(config_dir))
    assert info.pid != 2**22 + 999
    assert request(info.port, "GET", "/health")[0] == 200


def test_bind_is_logged_once_per_start(config_dir: Path) -> None:  # noqa: F811
    info = ensure_daemon(config_dir, spawner(config_dir))
    log = (state_dir(config_dir) / "daemon.log").read_text()
    assert log.count("\n") == 1
    assert f"bound 127.0.0.1:{info.port}" in log
