"""Event stream against a real daemon: 401, delivery within 2 s, replay, caps."""

import http.client
import json
import socket
import time
from collections.abc import Callable

from conftest import Served
from varde_learn.docs.pages.comments import append_comment

Factory = Callable[..., Served]


def open_stream(served: Served, headers: dict[str, str]) -> http.client.HTTPResponse:
    connection = http.client.HTTPConnection("127.0.0.1", served.port, timeout=5)
    connection.request("GET", "/api/events", headers=headers)
    return connection.getresponse()


def read_frame(response: http.client.HTTPResponse) -> dict[str, str]:
    """Read one SSE frame, skipping keepalive comments."""
    fields: dict[str, str] = {}
    while True:
        line = response.fp.readline().decode().rstrip("\n")  # type: ignore[union-attr]
        if line.startswith(":"):
            continue
        if not line:
            if fields:
                return fields
            continue
        key, _, value = line.partition(": ")
        fields[key] = value


def test_unauthenticated_events_are_401(served_factory: Factory) -> None:
    served = served_factory()
    status, _ = served.request(
        "GET", "/api/events", headers={"Host": f"127.0.0.1:{served.port}"}
    )
    assert status == 401


def test_new_comment_arrives_within_2s_and_replays(served_factory: Factory) -> None:
    served = served_factory()
    doc = served.working / "page.md"
    doc.write_text("# Page\n")
    time.sleep(0.5)  # let the watcher prime
    stream = open_stream(served, served.headers())
    assert stream.status == 200
    started = time.monotonic()
    append_comment(doc, "top", "", "hello")
    frame = read_frame(stream)
    assert time.monotonic() - started < 2
    assert frame["event"] == "doc.comment"
    first_id = frame["id"]
    stream.close()
    append_comment(doc, "top", "", "second")
    time.sleep(0.6)
    replay = open_stream(served, served.headers(**{"Last-Event-ID": first_id}))
    frame = read_frame(replay)
    assert frame["event"] == "doc.comment"
    assert json.loads(frame["data"])["data"]["text"] == "second"
    replay.close()


def test_foreign_cursor_gets_reset_frame(served_factory: Factory) -> None:
    served = served_factory()
    stream = open_stream(served, served.headers(**{"Last-Event-ID": "other:7"}))
    assert read_frame(stream)["event"] == "reset"
    stream.close()


def test_poll_cursor_flow_and_reset(served_factory: Factory) -> None:
    served = served_factory()
    _, first = served.request("GET", "/api/events/poll")
    assert first["events"] == []  # type: ignore[index]
    doc = served.working / "p.md"
    doc.write_text("# P\n")
    time.sleep(0.5)
    append_comment(doc, "top", "", "x")
    status, body = served.request(
        "GET",
        f"/api/events/poll?cursor={first['cursor']}&wait_s=3",  # type: ignore[index]
    )
    assert status == 200
    assert [e["kind"] for e in body["events"]] == ["doc.comment"]  # type: ignore[index]
    _, reset = served.request("GET", "/api/events/poll?cursor=bogus")
    assert reset["reset"] is True  # type: ignore[index]


def test_stream_cap_returns_429(served_factory: Factory) -> None:
    served = served_factory()
    held = [open_stream(served, served.headers()) for _ in range(16)]
    assert all(r.status == 200 for r in held)
    over = open_stream(served, served.headers())
    assert over.status == 429
    for response in held:
        response.close()
    time.sleep(1.5)
    again = open_stream(served, served.headers())
    assert again.status == 200
    again.close()


def test_open_stream_keeps_daemon_alive_past_idle(served_factory: Factory) -> None:
    served = served_factory("[serve]\nidle_s = 1\n")
    stream = open_stream(served, served.headers())
    time.sleep(7)  # idle checks run every min(5, idle_s)=1 s
    probe = socket.create_connection(("127.0.0.1", served.port), timeout=2)
    probe.close()
    stream.close()


def test_idle_daemon_exits(served_factory: Factory) -> None:
    from varde_serve.daemon.state import read_info
    from varde_serve.daemon.tokens import state_dir

    served = served_factory("[serve]\nidle_s = 1\n")
    deadline = time.monotonic() + 10
    while read_info(state_dir(served.config_dir)) is not None:
        assert time.monotonic() < deadline, "daemon did not exit when idle"
        time.sleep(0.2)
