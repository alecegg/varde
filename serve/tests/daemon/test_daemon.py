"""Daemon lifecycle and request gate against a real subprocess daemon."""

import contextlib
import http.client
import json
import os
import signal
import socket
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from varde_serve.daemon.lifecycle import ensure_daemon, spawn_daemon, stop_daemon
from varde_serve.daemon.state import read_info
from varde_serve.daemon.tokens import ensure_tokens, state_dir

LAUNCH = (
    "import sys; from pathlib import Path; "
    "from varde_serve.daemon.lifecycle import run_daemon; "
    "raise SystemExit(run_daemon(Path(sys.argv[1]), 'test'))"
)


def spawner(config_dir: Path):
    return lambda: spawn_daemon((sys.executable, "-c", LAUNCH, str(config_dir)))


def request(
    port: int,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: dict | None = None,
):
    base = {"Host": f"127.0.0.1:{port}"}
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    payload = json.dumps(body) if body is not None else None
    connection.request(method, path, payload, {**base, **(headers or {})})
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, data


@pytest.fixture
def config_dir(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "cfg"
    root.mkdir()
    yield root
    info = read_info(state_dir(root))
    if info is not None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(info.pid, signal.SIGKILL)


def test_health_bind_and_write_rejection(config_dir: Path) -> None:
    info = ensure_daemon(config_dir, spawner(config_dir))
    status, data = request(info.port, "GET", "/health")
    health = json.loads(data)
    assert status == 200
    assert set(health) == {"version", "api_version", "features", "pid"}
    assert health["pid"] == info.pid
    assert info.bind == "127.0.0.1"
    status, _ = request(info.port, "POST", "/api/queue/reorder", body={})
    assert status == 401
    # A non-loopback address must not reach the daemon.
    outside = socket.socket()
    outside.settimeout(1)
    try:
        address = socket.gethostbyname(socket.gethostname())
    except OSError:
        address = "127.0.0.1"
    if address != "127.0.0.1":
        assert outside.connect_ex((address, info.port)) != 0
    outside.close()


def test_host_origin_and_unauthenticated_events(config_dir: Path) -> None:
    info = ensure_daemon(config_dir, spawner(config_dir))
    assert request(info.port, "GET", "/health", {"Host": "evil.example"})[0] == 403
    cross = {"Origin": "http://evil.example"}
    assert request(info.port, "POST", "/auth/session", cross, {})[0] == 403
    assert request(info.port, "GET", "/api/events")[0] == 401
    assert request(info.port, "OPTIONS", "/health")[0] == 405


def test_write_gate_and_scopes(config_dir: Path) -> None:
    (config_dir / "config.toml").write_text("")
    info = ensure_daemon(config_dir, spawner(config_dir))
    tokens = ensure_tokens(config_dir)
    human = {"Authorization": f"Bearer {tokens.human}"}
    mcp = {"Authorization": f"Bearer {tokens.mcp}"}
    status, _ = request(info.port, "POST", "/x", human, {})
    assert status == 403  # allow_edit unset
    assert request(info.port, "POST", "/x", mcp, {})[0] == 403
    assert request(info.port, "POST", "/shutdown", mcp)[0] == 403
    assert stop_daemon(config_dir)
    deadline = time.monotonic() + 5
    while read_info(state_dir(config_dir)) is not None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert read_info(state_dir(config_dir)) is None


def test_allow_edit_config_opens_the_write_gate(config_dir: Path) -> None:
    (config_dir / "config.toml").write_text("[serve]\nallow_edit = true\n")
    info = ensure_daemon(config_dir, spawner(config_dir))
    tokens = ensure_tokens(config_dir)
    human = {"Authorization": f"Bearer {tokens.human}"}
    mcp = {"Authorization": f"Bearer {tokens.mcp}"}
    assert request(info.port, "POST", "/x", human, {})[0] == 404  # past the gate
    assert (
        request(info.port, "POST", "/x", mcp, {})[0] == 403
    )  # unknown write is human-only


def test_session_cookie_handshake_and_rate_limit(config_dir: Path) -> None:
    info = ensure_daemon(config_dir, spawner(config_dir))
    tokens = ensure_tokens(config_dir)
    for _ in range(5):
        assert (
            request(info.port, "POST", "/auth/session", body={"token": "bad"})[0] == 401
        )
    assert (
        request(info.port, "POST", "/auth/session", body={"token": tokens.human})[0]
        == 429
    )


def test_sigkilled_daemon_is_replaced_and_dead_info_not_trusted(
    config_dir: Path,
) -> None:
    first = ensure_daemon(config_dir, spawner(config_dir))
    os.kill(first.pid, signal.SIGKILL)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(first.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    second = ensure_daemon(config_dir, spawner(config_dir))
    assert second.pid != first.pid
    assert request(second.port, "GET", "/health")[0] == 200


def test_concurrent_starts_yield_one_daemon(config_dir: Path) -> None:
    results = []

    def start() -> None:
        results.append(ensure_daemon(config_dir, spawner(config_dir)).pid)

    threads = [threading.Thread(target=start) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(results)) == 1
