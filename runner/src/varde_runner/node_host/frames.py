"""JSON Lines frames of the Node host protocol (version 1)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from varde_runner.node_host.errors import FrameTooLarge

MAX_LINE_BYTES = 16 * 1024 * 1024
PROTOCOL_VERSION = 1


class FrameError(ValueError):
    """A host line is not a valid protocol frame."""


@dataclass(frozen=True, slots=True)
class Ready:
    protocol: int
    engine: str
    node: str


@dataclass(frozen=True, slots=True)
class Reply:
    id: int
    result: dict[str, Any] | None
    error: tuple[str, str] | None


@dataclass(frozen=True, slots=True)
class Event:
    event: str
    session: str | None
    data: dict[str, Any]
    seq: int


def encode_request(request_id: int, method: str, params: dict[str, Any]) -> bytes:
    line = json.dumps(
        {"id": request_id, "method": method, "params": params},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(line) + 1 > MAX_LINE_BYTES:
        raise FrameTooLarge(f"request {method} exceeds {MAX_LINE_BYTES} bytes")
    return line + b"\n"


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_ready(frame: dict[str, Any]) -> Ready:
    protocol, engine, node = (
        frame.get("protocol"),
        frame.get("engine"),
        frame.get("node"),
    )
    if not (
        isinstance(protocol, int)
        and not isinstance(protocol, bool)
        and isinstance(engine, str)
        and isinstance(node, str)
    ):
        raise FrameError("ready frame needs integer protocol and string engine, node")
    return Ready(protocol, engine, node)


def _parse_reply(frame: dict[str, Any]) -> Reply:
    result, error = frame.get("result"), frame.get("error")
    if isinstance(result, dict) and error is None:
        return Reply(frame["id"], result, None)
    code = error.get("code") if isinstance(error, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    if result is None and isinstance(code, str) and isinstance(message, str):
        return Reply(frame["id"], None, (code, message))
    raise FrameError("reply needs an object result or an error with code and message")


def _parse_event(frame: dict[str, Any]) -> Event:
    session, data, seq = frame.get("session"), frame.get("data"), frame.get("seq")
    name = frame["event"]
    if not (isinstance(name, str) and isinstance(data, dict)):
        raise FrameError("event needs a string event and object data")
    if not (session is None or isinstance(session, str)):
        raise FrameError("event session must be a string or null")
    if not isinstance(seq, int) or isinstance(seq, bool):
        raise FrameError("event seq must be an integer")
    return Event(name, session, data, seq)


def parse_frame(line: bytes) -> Ready | Reply | Event:
    try:
        frame = json.loads(line)
    except ValueError as exc:
        raise FrameError(f"invalid JSON: {exc}") from exc
    if not isinstance(frame, dict):
        raise FrameError("frame is not an object")
    if frame.get("type") == "ready":
        return _parse_ready(frame)
    if _is_int(frame.get("id")):
        return _parse_reply(frame)
    if "event" in frame:
        return _parse_event(frame)
    raise FrameError("frame is not ready, reply or event")
