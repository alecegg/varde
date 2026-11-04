from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from varde_data.chat import open_chat
from varde_data.records.chat import ChatBot
from varde_runner.chat_delivery import ChatDelivery
from varde_runner.supervisor import SendOutcome
from varde_runner.thread_keys import parse_thread_key
from varde_runner.web.chat_route import create_chat_routes


def request(app, method, path, payload=None, headers=()) -> tuple[int, Any]:
    body = json.dumps(payload).encode() if payload is not None else b""

    async def dispatch():
        raw_path, _, query = path.partition("?")
        messages = []
        consumed = False

        async def receive():
            nonlocal consumed
            if consumed:
                return {"type": "http.disconnect"}
            consumed = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": method,
                "scheme": "http",
                "path": raw_path,
                "raw_path": raw_path.encode(),
                "query_string": query.encode(),
                "root_path": "",
                "headers": [(b"host", b"localhost"), *headers],
                "client": ("127.0.0.1", 1),
                "server": ("localhost", 80),
            },
            receive,
            send,
        )
        start = next(
            message for message in messages if message["type"] == "http.response.start"
        )
        data = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        return start["status"], data

    status, data = asyncio.run(dispatch())
    return status, json.loads(data) if data.startswith(b"{") else data


class NoopDelivery(ChatDelivery):
    def __init__(self) -> None:
        pass

    async def accept(self, message):
        return None


def test_thread_keys_allow_main_and_registered_instance_shapes():
    main = parse_thread_key("main")
    instance = parse_thread_key("instance:agent-1")
    assert main is not None and main.kind == "main"
    assert instance is not None and instance.agent_id == "agent-1"
    for invalid in (
        None,
        "",
        "MAIN",
        "instance:",
        "instance:../x",
        "instance:a/b",
        "other:agent",
    ):
        assert parse_thread_key(invalid) is None


def test_history_validation_replay_and_reply_target(tmp_path):
    chat = open_chat(tmp_path)
    chat.create_thread("instance:agent-1", agent_id="agent-1", label="Worker")
    chat.append_event("handoff", "summary", "/notes", "main")
    app = Starlette(routes=create_chat_routes(chat, NoopDelivery()))

    status, response = request(app, "GET", "/api/chat")
    assert status == 200
    assert response["thread"]["state"] == "unavailable"
    assert len(response["messages"]) == 1
    assert response["messages"][0]["role"] == "event"
    assert request(app, "GET", "/api/chat?thread=instance:unknown")[0] == 404
    assert request(app, "GET", "/api/chat?thread=bad-key")[0] == 404

    status, first = request(
        app,
        "POST",
        "/api/chat/messages",
        {"client_msg_id": "m-1", "text": "hello", "thread": "main"},
    )
    assert status == 202
    status, replay = request(
        app,
        "POST",
        "/api/chat/messages",
        {"client_msg_id": "m-1", "text": "hello again", "thread": "main"},
    )
    assert status == 200 and replay == first
    assert chat.page("main")[-1].text == "hello"

    assert (
        request(
            app,
            "POST",
            "/api/chat/messages",
            {
                "client_msg_id": "m-2",
                "text": "reply",
                "reply_to": chat.page("main")[0].id,
            },
        )[0]
        == 400
    )
    assert (
        request(
            app,
            "POST",
            "/api/chat/messages",
            {"client_msg_id": "m-3", "text": " "},
        )[0]
        == 400
    )
    assert (
        request(
            app,
            "POST",
            "/api/chat/messages",
            {"client_msg_id": "m-4", "text": "x" * 20_001},
        )[0]
        == 400
    )

    chat.create_thread("instance:agent-2", agent_id="agent-2")
    user = chat.append_user("instance:agent-2", "replyable", "a question")
    status, reply = request(
        app,
        "POST",
        "/api/chat/messages",
        {
            "client_msg_id": "m-5",
            "text": "answer",
            "thread": "instance:agent-2",
            "reply_to": "replyable",
        },
    )
    assert status == 202 and reply["seq"] > user.seq


def test_stream_resume_uses_last_event_id_and_emits_full_current_rows(tmp_path):
    chat = open_chat(tmp_path)
    row = chat.append_bot("main", "manager", 1, "first", state="streaming")
    chat.update_bot_text("main", row.id, "final answer", state="final")
    routes = create_chat_routes(chat, NoopDelivery())
    endpoint = routes[2].endpoint

    async def read_first_event():
        async def receive():
            return {"type": "http.disconnect"}

        request_obj = Request(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/chat/stream",
                "raw_path": b"/api/chat/stream",
                "query_string": b"after=999",
                "root_path": "",
                "headers": [(b"last-event-id", b"0")],
                "client": ("127.0.0.1", 1),
                "server": ("localhost", 80),
            },
            receive,
        )
        response = await endpoint(request_obj)
        frame = await anext(response.body_iterator)
        await response.body_iterator.aclose()
        return response, frame

    response, frame = asyncio.run(read_first_event())
    assert response.media_type == "text/event-stream"
    assert frame.startswith(b"id: 2\nevent: message\n")
    assert b"final answer" in frame


class FakeSupervisor:
    def __init__(self, outcomes, events=()):
        self.outcomes = iter(outcomes)
        self.events = list(events)
        self.calls = []
        self.store = SimpleNamespace(get_session=lambda _session: {"last_event_seq": 7})

    def resolve_session(self, agent_id: str) -> dict[str, str] | None:
        return {"id": agent_id}

    async def send(self, agent_id, text, *, client_id):
        self.calls.append((agent_id, text, client_id))
        return next(self.outcomes)

    async def watch(self, *_args, **_kwargs):
        for event in self.events:
            yield {"type": "event", **event}
        await asyncio.sleep(60)
        if False:
            yield {}


async def get_supervisor(supervisor):
    return supervisor


def test_delivery_retries_busy_and_replaced_target_once_in_order(tmp_path):
    async def run():
        chat = open_chat(tmp_path)
        first = chat.append_user("main", "m-1", "first")
        second = chat.append_user("main", "m-2", "second")
        chat.set_chat_bot("main", "manager", "now", None, "running", 1)
        supervisor = FakeSupervisor(
            [SendOutcome.SKIPPED_BUSY, SendOutcome.SENT, SendOutcome.SENT]
        )
        delivery = ChatDelivery(
            chat, lambda: get_supervisor(supervisor), retry_seconds=0.001
        )
        await delivery.accept(first)
        await delivery.accept(second)
        for _ in range(100):
            if len(supervisor.calls) == 3:
                break
            await asyncio.sleep(0.002)
        await delivery.accept(first)
        assert [call[1] for call in supervisor.calls] == ["first", "first", "second"]
        assert [call[2] for call in supervisor.calls] == ["system:dashboard"] * 3
        assert chat.get_chat_bot("main") == ChatBot(
            "main", "manager", "now", None, "running", 1
        )
        await delivery.close()

    asyncio.run(run())


def test_missing_target_remains_queued_until_replaced(tmp_path):
    async def run():
        chat = open_chat(tmp_path)
        row = chat.append_user("main", "m-1", "waiting")
        supervisor = FakeSupervisor([SendOutcome.SENT])
        target_ready = False

        def resolve():
            return supervisor

        original_resolve = supervisor.resolve_session
        supervisor.resolve_session = lambda agent_id: (
            original_resolve(agent_id) if target_ready else None
        )
        delivery = ChatDelivery(
            chat, lambda: get_supervisor(resolve()), retry_seconds=0.001
        )
        await delivery.accept(row)
        chat.set_chat_bot("main", "replacement", "now", None, "running", 2)
        target_ready = True
        for _ in range(100):
            if supervisor.calls:
                break
            await asyncio.sleep(0.002)
        assert supervisor.calls == [("replacement", "waiting", "system:dashboard")]
        await delivery.close()

    asyncio.run(run())


def test_delivery_queue_recovers_after_restart_without_resending_completed_rows(
    tmp_path,
):
    async def run():
        chat = open_chat(tmp_path)
        row = chat.append_user("main", "m-1", "survive restart")
        chat.set_chat_bot("main", "manager", "now", None, "running", 1)
        first_supervisor = FakeSupervisor([])
        first_supervisor.resolve_session = lambda agent_id: None
        first_delivery = ChatDelivery(
            chat, lambda: get_supervisor(first_supervisor), retry_seconds=0.001
        )
        await first_delivery.accept(row)
        await asyncio.sleep(0.005)
        await first_delivery.close()

        reopened = open_chat(tmp_path)
        resumed_supervisor = FakeSupervisor([SendOutcome.SENT])
        resumed_delivery = ChatDelivery(
            reopened, lambda: get_supervisor(resumed_supervisor), retry_seconds=0.001
        )
        await resumed_delivery.start()
        for _ in range(100):
            if resumed_supervisor.calls and not reopened.pending_user_messages():
                break
            await asyncio.sleep(0.002)
        assert resumed_supervisor.calls == [
            ("manager", "survive restart", "system:dashboard")
        ]
        assert reopened.pending_user_messages() == ()
        await resumed_delivery.close()

        final_delivery = ChatDelivery(
            open_chat(tmp_path), lambda: get_supervisor(resumed_supervisor)
        )
        await final_delivery.start()
        assert len(resumed_supervisor.calls) == 1
        await final_delivery.close()

    asyncio.run(run())


def test_chat_owned_turn_projects_streamed_text_and_records_its_end(tmp_path):
    async def run():
        chat = open_chat(tmp_path)
        chat.set_chat_bot("main", "manager", "now", None, "running", 1)
        chat.append_user("main", "m-1", "say hello")
        supervisor = FakeSupervisor(
            [SendOutcome.SENT],
            [
                {"seq": 8, "kind": "text_delta", "payload": {"text": "Hello "}},
                {"seq": 9, "kind": "text_delta", "payload": {"text": "world"}},
                {"seq": 10, "kind": "text", "payload": {"text": "Hello world"}},
                {"seq": 11, "kind": "status", "payload": {"status": "idle"}},
            ],
        )
        delivery = ChatDelivery(
            chat, lambda: get_supervisor(supervisor), retry_seconds=0.001
        )
        await delivery.accept(chat.page("main")[-1])
        for _ in range(100):
            rows = chat.page("main")
            if any(row.role == "bot" and row.state == "final" for row in rows):
                break
            await asyncio.sleep(0.002)
        bot_rows = [row for row in chat.page("main") if row.role == "bot"]
        assert len(bot_rows) == 1
        assert bot_rows[0].text == "Hello world"
        assert bot_rows[0].state == "final"
        assert chat.record_turn("main", "manager", 8, 11).last_event_seq == 11
        await delivery.close()

    asyncio.run(run())
