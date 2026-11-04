"""HTTP history, send and change stream for registered chat threads."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
from varde_data.errors import Invalid, NotFound
from varde_data.records.chat import ChatThread
from varde_data.repos.chat import ChatRepository

from varde_runner.chat_delivery import ChatDelivery
from varde_runner.thread_keys import parse_thread_key

KEEPALIVE_SECONDS = 15.0
MAX_MESSAGE_CHARS = 20_000


def _thread(repository: ChatRepository, value: object) -> ChatThread | None:
    parsed = parse_thread_key(value)
    if parsed is None:
        return None
    try:
        row = repository.get_thread(parsed.key)
    except NotFound:
        return None
    if row.kind != parsed.kind or (parsed.agent_id and row.agent_id != parsed.agent_id):
        return None
    return row


def _message_json(message: Any) -> dict[str, Any]:
    return asdict(message)


def _bot_json(repository: ChatRepository, thread_key: str) -> dict[str, Any]:
    bot = repository.get_chat_bot(thread_key)
    if bot is None:
        return {"state": "unavailable", "context_pct": None, "generation": 0}
    return {"state": bot.state, "context_pct": None, "generation": bot.generation}


def _sse(event: str, payload: Any, event_id: int | None = None) -> bytes:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    lines.append(f"data: {data}")
    return ("\n".join(lines) + "\n\n").encode()


async def _history(request: Request, repository: ChatRepository) -> JSONResponse:
    key = request.query_params.get("thread", "main")
    thread = _thread(repository, key)
    if thread is None:
        return JSONResponse({"error": "thread not found"}, status_code=404)
    try:
        before_raw = request.query_params.get("before")
        before = int(before_raw) if before_raw is not None else None
        limit = int(request.query_params.get("limit", "50"))
    except ValueError:
        return JSONResponse({"error": "invalid page cursor"}, status_code=400)
    if (before is not None and before < 1) or not 1 <= limit <= 100:
        return JSONResponse({"error": "invalid page cursor"}, status_code=400)
    try:
        rows = repository.page(key, before, limit)
        latest = repository.page(key, None, 1)
        bot = _bot_json(repository, key)
    except NotFound:
        return JSONResponse({"error": "thread not found"}, status_code=404)
    state = "archived" if thread.archived_at else bot["state"]
    return JSONResponse(
        {
            "messages": [_message_json(row) for row in rows],
            "latest_seq": latest[-1].seq if latest else 0,
            "thread": {
                "key": thread.thread_key,
                "kind": thread.kind,
                "label": thread.label,
                "state": state,
            },
            "bot": bot,
        }
    )


def _validated_send(payload: object):
    if not isinstance(payload, dict):
        return JSONResponse({"error": "expected an object"}, status_code=400)
    message_id = payload.get("client_msg_id")
    text = payload.get("text")
    key = payload.get("thread", "main")
    reply_to = payload.get("reply_to")
    if not isinstance(message_id, str) or not message_id:
        return JSONResponse({"error": "client_msg_id is required"}, status_code=400)
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_MESSAGE_CHARS:
        return JSONResponse(
            {"error": "text must contain 1 to 20000 characters"}, status_code=400
        )
    if reply_to is not None and not isinstance(reply_to, str):
        return JSONResponse({"error": "reply_to must be a message id"}, status_code=400)
    return message_id, text, key, reply_to


async def _send_message(
    request: Request, repository: ChatRepository, delivery: ChatDelivery
) -> JSONResponse:
    try:
        payload = await request.json()
    except json.JSONDecodeError, UnicodeDecodeError:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    validated = _validated_send(payload)
    if isinstance(validated, JSONResponse):
        return validated
    message_id, text, key, reply_to = validated
    thread = _thread(repository, key)
    if thread is None:
        return JSONResponse({"error": "thread not found"}, status_code=404)
    try:
        message, created = repository.append_user_once(
            thread.thread_key, message_id, text, reply_to
        )
    except Invalid as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except NotFound:
        return JSONResponse({"error": "thread not found"}, status_code=404)
    if created:
        await delivery.accept(message)
    return JSONResponse(
        {"id": message.id, "seq": message.seq},
        status_code=202 if created else 200,
    )


def _after_cursor(request: Request) -> int | None:
    raw = request.headers.get("last-event-id")
    if raw is None:
        raw = request.query_params.get("after", "0")
    try:
        cursor = int(raw)
    except TypeError, ValueError:
        return None
    return cursor if cursor >= 0 else None


async def _stream_events(
    request: Request,
    repository: ChatRepository,
    key: str,
    cursor: int,
    keepalive_seconds: float,
) -> AsyncIterator[bytes]:
    last_keepalive = time.monotonic()
    known: dict[str, tuple[str, str, int]] = {}
    bot_state: tuple[Any, ...] | None = None
    while True:
        rows = repository.changes_after(key, cursor)
        for row in rows:
            previous = known.get(row.id)
            if (
                previous is not None
                and row.role == "bot"
                and row.text.startswith(previous[0])
                and len(row.text) > len(previous[0])
            ):
                yield _sse(
                    "delta",
                    {
                        "id": row.id,
                        "rev": row.change_seq,
                        "text_append": row.text[len(previous[0]) :],
                    },
                    row.change_seq,
                )
            else:
                yield _sse("message", _message_json(row), row.change_seq)
            known[row.id] = (row.text, row.state, row.change_seq)
            cursor = max(cursor, row.change_seq)
        bot = _bot_json(repository, key)
        state = (bot["state"], bot["context_pct"], bot["generation"])
        if state != bot_state:
            yield _sse("bot", bot)
            bot_state = state
        now = time.monotonic()
        if now - last_keepalive >= keepalive_seconds:
            yield b": keepalive\n\n"
            last_keepalive = now
        if await request.is_disconnected():
            return
        await asyncio.sleep(min(0.25, keepalive_seconds))


async def _stream(
    request: Request, repository: ChatRepository, keepalive_seconds: float
) -> JSONResponse | StreamingResponse:
    key = request.query_params.get("thread", "main")
    if _thread(repository, key) is None:
        return JSONResponse({"error": "thread not found"}, status_code=404)
    cursor = _after_cursor(request)
    if cursor is None:
        return JSONResponse({"error": "invalid change cursor"}, status_code=400)
    return StreamingResponse(
        _stream_events(request, repository, key, cursor, keepalive_seconds),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


def create_chat_routes(
    repository: ChatRepository,
    delivery: ChatDelivery,
    *,
    keepalive_seconds: float = KEEPALIVE_SECONDS,
) -> list[Route]:
    async def history(request: Request) -> JSONResponse:
        return await _history(request, repository)

    async def send_message(request: Request) -> JSONResponse:
        return await _send_message(request, repository, delivery)

    async def stream(request: Request) -> JSONResponse | StreamingResponse:
        return await _stream(request, repository, keepalive_seconds)

    return [
        Route("/api/chat", history, methods=["GET"]),
        Route("/api/chat/messages", send_message, methods=["POST"]),
        Route("/api/chat/stream", stream, methods=["GET"]),
    ]
