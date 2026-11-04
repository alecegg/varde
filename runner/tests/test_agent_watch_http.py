from __future__ import annotations

import asyncio
import http.client
import io
import json
import sys
from collections.abc import AsyncGenerator
from typing import cast
from urllib import request as urllib_request
from urllib.parse import urlencode

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from test_send_path import FakePlugin
from varde_runner import main
from varde_runner.clients import ClientRole, ObserverReadOnly
from varde_runner.plugins import SessionSpec
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.supervisor import Supervisor
from varde_runner.web.agent_watch import create_agent_watch_route
from varde_runner.web.app import RequestTimingMiddleware, create_app


async def _supervisor(tmp_path):
    supervisor = Supervisor(tmp_path / "sessions", {"fake": FakePlugin()})
    session = await supervisor.start_session(
        SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
    )
    return supervisor, session.session_id


def _get_supervisor(supervisor):
    async def get():
        return supervisor

    return get


def _request(route, query: dict[str, str]):
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/agents/agent/watch",
        "raw_path": b"/api/agents/agent/watch",
        "query_string": urlencode(query).encode(),
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 8765),
        "path_params": {"id": "agent"},
    }
    return Request(scope)


def _response_stream(response: StreamingResponse) -> AsyncGenerator[bytes]:
    return cast("AsyncGenerator[bytes]", response.body_iterator)


async def _asgi_request(
    app,
    path: str,
    *,
    query: str = "",
    host: str = "127.0.0.1:8765",
    disconnect_after_first_body: bool = False,
    on_body=None,
):
    messages = []
    disconnect = asyncio.Event()
    first_receive = True

    async def receive():
        nonlocal first_receive
        if first_receive:
            first_receive = False
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            if on_body is not None:
                on_body(message["body"])
            if disconnect_after_first_body:
                disconnect.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": [(b"host", host.encode())],
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 8765),
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=3)
    return messages


def test_watch_route_sends_snapshot_then_incremental_event(tmp_path):
    async def exercise():
        supervisor, session_id = await _supervisor(tmp_path)
        route = create_agent_watch_route(_get_supervisor(supervisor))
        supervisor.store.update_session(session_id, agent_id="agent")
        resolved = supervisor.resolve_session("agent")
        assert resolved is not None and resolved["id"] == session_id
        assert supervisor.resolve_session("missing") is None
        response = await route.endpoint(
            _request(route, {"client": "browser", "role": "writer"})
        )
        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"
        stream = _response_stream(response)
        first = await asyncio.wait_for(anext(stream), timeout=0.2)
        assert first.startswith(b"event: snapshot\ndata: ")
        first_payload = json.loads(first.split(b"data: ", 1)[1])
        assert first_payload["type"] == "snapshot"

        next_frame = asyncio.ensure_future(anext(stream))
        await supervisor.record_event(session_id, "message", {"text": "hello"})
        event = await asyncio.wait_for(next_frame, timeout=0.2)
        assert event.startswith(b"event: event\ndata: ")
        assert json.loads(event.split(b"data: ", 1)[1])["payload"] == {"text": "hello"}
        await stream.aclose()

    asyncio.run(exercise())


def test_watch_route_resumes_after_cursor_and_first_frame_is_incremental(tmp_path):
    async def exercise():
        supervisor, session_id = await _supervisor(tmp_path)
        supervisor.store.update_session(session_id, agent_id="agent")
        await supervisor.record_event(session_id, "message", {"n": 1})
        route = create_agent_watch_route(_get_supervisor(supervisor))
        response = await route.endpoint(
            _request(
                route,
                {"after": "1", "client": "reader", "role": "observer"},
            )
        )
        assert isinstance(response, StreamingResponse)
        stream = _response_stream(response)
        next_frame = asyncio.ensure_future(anext(stream))
        await supervisor.record_event(session_id, "message", {"n": 2})
        first = await asyncio.wait_for(next_frame, timeout=0.2)
        assert first.startswith(b"event: event\ndata: ")
        assert json.loads(first.split(b"data: ", 1)[1])["seq"] == 2
        await stream.aclose()

    asyncio.run(exercise())


def test_watch_route_sends_keepalive_while_waiting(tmp_path):
    async def exercise():
        supervisor, session_id = await _supervisor(tmp_path)
        supervisor.store.update_session(session_id, agent_id="agent")
        route = create_agent_watch_route(
            _get_supervisor(supervisor), keepalive_seconds=0.001
        )
        response = await route.endpoint(
            _request(route, {"client": "reader", "role": "observer"})
        )
        assert isinstance(response, StreamingResponse)
        stream = _response_stream(response)
        assert (await anext(stream)).startswith(b"event: snapshot")
        assert await asyncio.wait_for(anext(stream), timeout=0.2) == b": keepalive\n\n"
        await stream.aclose()

    asyncio.run(exercise())


def test_watch_timing_is_logged_when_response_starts(caplog):
    async def exercise():
        caplog.set_level("INFO", logger="varde_runner.web.app")
        response_started = asyncio.Event()
        finish_response = asyncio.Event()

        async def streaming_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            response_started.set()
            await finish_response.wait()
            await send({"type": "http.response.body", "body": b"", "more_body": False})

        async def send(message):
            return None

        middleware = RequestTimingMiddleware(streaming_app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/agents/agent-1/watch",
        }
        request = asyncio.create_task(middleware(scope, None, send))
        await response_started.wait()
        try:
            assert any(
                "/api/agents/agent-1/watch" in record.getMessage()
                for record in caplog.records
            )
        finally:
            finish_response.set()
        await request

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("agent_id", "query", "status"),
    [
        ("missing", {"client": "c", "role": "writer"}, 404),
        ("agent", {"client": "c", "role": "invalid"}, 400),
        ("agent", {"client": "c", "role": "observer", "after": "bad"}, 400),
    ],
)
def test_watch_route_rejects_unknown_or_invalid_request(
    tmp_path, agent_id, query, status
):
    async def exercise():
        supervisor, session_id = await _supervisor(tmp_path)
        supervisor.store.update_session(session_id, agent_id="agent")
        route = create_agent_watch_route(_get_supervisor(supervisor))
        request = _request(route, query)
        request.scope["path_params"]["id"] = agent_id
        response = await route.endpoint(request)
        assert isinstance(response, JSONResponse)
        assert response.status_code == status

    asyncio.run(exercise())


def test_observer_http_watch_attaches_before_write_is_checked(tmp_path):
    async def exercise():
        supervisor, session_id = await _supervisor(tmp_path)
        supervisor.store.update_session(session_id, agent_id="agent")
        route = create_agent_watch_route(_get_supervisor(supervisor))
        response = await route.endpoint(
            _request(route, {"client": "observer", "role": "observer"})
        )
        assert isinstance(response, StreamingResponse)
        stream = _response_stream(response)
        await asyncio.wait_for(anext(stream), timeout=0.2)
        with pytest.raises(ObserverReadOnly):
            await supervisor.send(session_id, "blocked", client_id="observer")
        await stream.aclose()

    asyncio.run(exercise())


def test_create_app_watch_disconnect_detaches_observer_and_releases_lease(
    tmp_path, monkeypatch
):
    async def exercise():
        plugin = FakePlugin()
        registry = PluginRegistry()
        registry.register("fake", plugin, provider_key="fake")
        monkeypatch.setattr("varde_runner.web.app.build_registry", lambda: registry)
        app = create_app(data_dir=tmp_path, bound_port=8765)

        missing = await _asgi_request(
            app,
            "/api/agents/missing/watch",
            query="client=init&role=observer",
        )
        assert (
            next(
                message["status"]
                for message in missing
                if message["type"] == "http.response.start"
            )
            == 404
        )

        supervisor = app.state.supervisor
        ref = await supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
        session_id = ref.session_id
        client_id = "observer-http"
        supervisor.writer_leases.acquire(session_id, client_id)
        registration_at_frame = []

        def on_body(body):
            if b"event: snapshot\n" in body:
                registration_at_frame.append(
                    supervisor.clients.role(session_id, client_id)
                )

        response = await _asgi_request(
            app,
            f"/api/agents/{session_id}/watch",
            query=f"client={client_id}&role=observer",
            disconnect_after_first_body=True,
            on_body=on_body,
        )
        assert (
            next(
                message["status"]
                for message in response
                if message["type"] == "http.response.start"
            )
            == 200
        )
        assert registration_at_frame == [ClientRole.OBSERVER]
        assert any(
            b"event: snapshot\n" in message.get("body", b"")
            for message in response
            if message["type"] == "http.response.body"
        )
        assert supervisor.clients.role(session_id, client_id) is None
        assert supervisor.writer_leases.holder(session_id) is None
        await supervisor.shutdown()

    asyncio.run(exercise())


def test_create_app_watch_rejects_bad_host(tmp_path):
    app = create_app(data_dir=tmp_path, bound_port=8765)
    response = asyncio.run(
        _asgi_request(
            app,
            "/api/agents/agent/watch",
            query="client=observer&role=observer",
            host="bad.example:8765",
        )
    )
    assert (
        next(
            message["status"]
            for message in response
            if message["type"] == "http.response.start"
        )
        == 403
    )


def test_watch_route_emits_error_when_attach_races_role_precheck(tmp_path, monkeypatch):
    async def exercise():
        supervisor, session_id = await _supervisor(tmp_path)
        supervisor.store.update_session(session_id, agent_id="agent")

        def reject_attach(*args, **kwargs):
            raise ValueError("client is already attached with another role")

        monkeypatch.setattr(supervisor.clients, "attach", reject_attach)
        route = create_agent_watch_route(_get_supervisor(supervisor))
        response = await route.endpoint(
            _request(route, {"client": "racing-client", "role": "writer"})
        )
        assert isinstance(response, StreamingResponse)
        stream = _response_stream(response)
        frame = await anext(stream)
        assert frame.startswith(b"event: error\ndata: ")
        assert json.loads(frame.split(b"data: ", 1)[1]) == {
            "error": "client is already attached with another role"
        }
        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    asyncio.run(exercise())


def test_watch_cli_prints_each_sse_data_frame_as_json(monkeypatch, capsys):
    payload = {"type": "snapshot", "last_seq": 0}
    body = (
        b": keepalive\n\nevent: snapshot\ndata: "
        + json.dumps(payload, separators=(",", ":")).encode()
        + b"\n\n"
    )

    class Opener:
        def open(self, url):
            self.url = url
            return io.BytesIO(body)

    opener = Opener()
    handlers = []

    def build_opener(*values):
        handlers.extend(values)
        return opener

    monkeypatch.setattr(urllib_request, "build_opener", build_opener)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "varde-runner",
            "watch",
            "agent-1",
            "--writer",
            "--after",
            "2",
            "--port",
            "8766",
        ],
    )
    main()
    assert capsys.readouterr().out == json.dumps(payload, separators=(",", ":")) + "\n"
    assert opener.url.startswith("http://127.0.0.1:8766/")
    assert "role=writer" in opener.url
    assert any(
        isinstance(handler, urllib_request.ProxyHandler)
        and vars(handler).get("proxies") == {}
        for handler in handlers
    )


def test_watch_cli_defaults_to_observer(monkeypatch):
    class Opener:
        def open(self, url):
            self.url = url
            return io.BytesIO(b"")

    opener = Opener()
    monkeypatch.setattr(urllib_request, "build_opener", lambda *args: opener)
    monkeypatch.setattr(sys, "argv", ["varde-runner", "watch", "agent-1"])

    main()

    assert "role=observer" in opener.url


@pytest.mark.parametrize(
    "exception", [OSError("reset"), http.client.IncompleteRead(b"partial")]
)
def test_watch_cli_handles_stream_drops(monkeypatch, exception):
    class BrokenStream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return self

        def __next__(self):
            raise exception

    class Opener:
        def open(self, url):
            return BrokenStream()

    monkeypatch.setattr(urllib_request, "build_opener", lambda *args: Opener())
    monkeypatch.setattr(sys, "argv", ["varde-runner", "watch", "agent"])
    with pytest.raises(SystemExit, match="watch stream interrupted"):
        main()


def test_watch_cli_handles_keyboard_interrupt_quietly(monkeypatch, capsys):
    class InterruptedStream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return self

        def __next__(self):
            raise KeyboardInterrupt

    class Opener:
        def open(self, url):
            return InterruptedStream()

    monkeypatch.setattr(urllib_request, "build_opener", lambda *args: Opener())
    monkeypatch.setattr(sys, "argv", ["varde-runner", "watch", "agent"])
    with pytest.raises(SystemExit) as raised:
        main()
    assert raised.value.code == 130
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize(
    "option",
    [["--host", "127.0.0.1"], ["--allowed-host", "localhost"]],
)
def test_watch_cli_rejects_serve_only_options(monkeypatch, option):
    monkeypatch.setattr(sys, "argv", ["varde-runner", "watch", "agent", *option])
    with pytest.raises(SystemExit) as raised:
        main()
    assert raised.value.code == 2


def test_writer_option_requires_watch_command(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["varde-runner", "serve", "--writer"])
    with pytest.raises(SystemExit) as raised:
        main()
    assert raised.value.code == 2


def _bot_request(session_id: str, actor: str, query: dict[str, str]):
    from varde_runner.bot_tokens import BotIdentity

    request = _request(None, query)
    request.scope["path_params"] = {"id": session_id}
    request.scope["bot_identity"] = BotIdentity(actor, "s")
    return request


def test_bot_watch_is_limited_to_visible_agents_with_a_server_derived_client(
    tmp_path, monkeypatch
):
    asyncio.run(_bot_watch_exercise(tmp_path, monkeypatch))


async def _bot_watch_exercise(tmp_path, monkeypatch):
    from varde_runner.web import agent_watch

    supervisor, session_id = await _supervisor(tmp_path)
    route = create_agent_watch_route(_get_supervisor(supervisor))
    chosen = {"client": "mine", "role": "writer"}

    async def rows(_supervisor):
        return [
            {
                "session_id": "other",
                "agent_id": "a-other",
                "parent_id": None,
                "launched_by": "bot:manager",
            }
        ]

    monkeypatch.setattr(agent_watch, "_agent_rows", rows)
    for actor in ("bot:manager", "bot:manager/someone-else"):
        response = await route.endpoint(_bot_request(session_id, actor, chosen))
        assert response.status_code == 404
    assert supervisor.clients.role(session_id, "mine") is None

    async def visible(_supervisor):
        return [
            {
                "session_id": session_id,
                "agent_id": "a1",
                "parent_id": None,
                "launched_by": "bot:manager",
            }
        ]

    monkeypatch.setattr(agent_watch, "_agent_rows", visible)
    response = await route.endpoint(_bot_request(session_id, "bot:manager", chosen))
    assert isinstance(response, StreamingResponse)
    await _response_stream(response).aclose()
