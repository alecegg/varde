from __future__ import annotations

import json

import pytest
from varde_runner.node_host import FrameTooLarge
from varde_runner.node_host.frames import (
    MAX_LINE_BYTES,
    Event,
    FrameError,
    Ready,
    Reply,
    encode_request,
    parse_frame,
)
from varde_runner.node_host.node_version import node_version_supported


def test_encode_request_is_one_line() -> None:
    line = encode_request(7, "echo", {"text": "a\nb"})
    assert line.endswith(b"\n")
    assert line.count(b"\n") == 1
    assert json.loads(line) == {"id": 7, "method": "echo", "params": {"text": "a\nb"}}


def test_encode_rejects_oversize_request() -> None:
    with pytest.raises(FrameTooLarge):
        encode_request(1, "echo", {"blob": "x" * MAX_LINE_BYTES})


def test_parse_ready_reply_error_event() -> None:
    assert parse_frame(
        b'{"type":"ready","protocol":1,"engine":"e","node":"22.19.0"}'
    ) == Ready(1, "e", "22.19.0")
    assert parse_frame(b'{"id":3,"result":{"a":1}}') == Reply(3, {"a": 1}, None)
    assert parse_frame(b'{"id":3,"error":{"code":"c","message":"m"}}') == Reply(
        3, None, ("c", "m")
    )
    assert parse_frame(b'{"event":"x","session":null,"data":{},"seq":4}') == Event(
        "x", None, {}, 4
    )


@pytest.mark.parametrize(
    "line",
    [
        b"not json",
        b"[1]",
        b'{"id":true,"result":{}}',
        b'{"id":1}',
        b'{"id":1,"result":5}',
        b'{"id":1,"error":{"code":1,"message":"m"}}',
        b'{"event":"x","session":3,"data":{},"seq":1}',
        b'{"event":"x","session":null,"data":{},"seq":"1"}',
        b'{"type":"ready","protocol":"1","engine":"e","node":"22"}',
        b'{"other":1}',
    ],
)
def test_parse_rejects_malformed(line: bytes) -> None:
    with pytest.raises(FrameError):
        parse_frame(line)


@pytest.mark.parametrize(
    ("version", "ok"),
    [
        ("22.19.0", True),
        ("22.18.9", False),
        ("23.0.0", True),
        ("20.11.1", False),
        ("x", False),
    ],
)
def test_node_version_gate(version: str, ok: bool) -> None:
    assert node_version_supported(version) is ok
