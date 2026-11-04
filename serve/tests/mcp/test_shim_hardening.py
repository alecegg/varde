"""The shim holds only the mcp token, survives failures and answers ping."""

import io
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import Served
from varde_serve.daemon.tokens import TokenMissing, read_mcp_token
from varde_serve.mcp import shim
from varde_serve.mcp.shim import daemon_call, serve_stdio


def test_shim_works_with_the_human_token_unreadable(
    served_factory: Callable[..., Served],
) -> None:
    served = served_factory()
    human = served.config_dir / "serve" / "token"
    human.chmod(0o000)
    try:
        if os.access(human, os.R_OK):  # running as root: the denial cannot hold
            pytest.skip("cannot deny read to this user")
        call = daemon_call(served.config_dir, "test")
        is_error, payload = call("varde_read", {"resource": "plans"})
        assert not is_error, payload
    finally:
        human.chmod(0o600)


def test_read_mcp_token_never_creates_a_file(tmp_path: Path) -> None:
    with pytest.raises(TokenMissing):
        read_mcp_token(tmp_path)
    assert not (tmp_path / "serve").exists()


class Lines(io.StringIO):
    """A stdout that records each JSON reply and signals when ids arrive."""

    def __init__(self) -> None:
        super().__init__()
        self.replies: list[dict] = []
        self.seen: dict[object, threading.Event] = {
            1: threading.Event(),
            2: threading.Event(),
        }

    def write(self, text: str) -> int:
        for line in text.splitlines():
            reply = json.loads(line)
            self.replies.append(reply)
            self.seen.get(reply.get("id"), threading.Event()).set()
        return len(text)


def rpc(message_id: int, method: str, **params: object) -> dict:
    return {"jsonrpc": "2.0", "id": message_id, "method": method, "params": params}


def run_stdio(messages: list[dict], call, stdout: Lines | None = None) -> Lines:
    out = stdout or Lines()
    serve_stdio(io.StringIO("".join(json.dumps(m) + "\n" for m in messages)), out, call)
    return out


def test_ping_is_answered_while_a_tool_call_is_pending() -> None:
    out = Lines()

    def slow_call(tool: str, arguments: dict) -> tuple[bool, object]:
        assert out.seen[2].wait(5), "ping was blocked by the pending call"
        return False, {"done": True}

    run_stdio(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "varde_events"},
            },
            rpc(2, "ping"),
        ],
        slow_call,
        out,
    )
    assert [r["id"] for r in out.replies] == [2, 1]


def test_a_crashing_call_is_a_jsonrpc_error_and_the_loop_continues() -> None:
    def broken(tool: str, arguments: dict) -> tuple[bool, object]:
        raise KeyError("pid")

    out = run_stdio(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "x"},
            },
            rpc(2, "ping"),
        ],
        broken,
    )
    by_id = {r["id"]: r for r in out.replies}
    assert by_id[1]["error"]["code"] == -32603
    assert by_id[2]["result"] == {}


@pytest.mark.parametrize(
    "failure", [KeyError("pid"), ValueError("bad json"), PermissionError("token")]
)
def test_daemon_call_turns_any_failure_into_an_error_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def explode(config_dir: Path, version: str):
        raise failure

    monkeypatch.setattr(shim, "ensure_current_daemon", explode)
    is_error, payload = daemon_call(tmp_path, "v")("varde_read", {"resource": "plans"})
    assert is_error
    assert type(failure).__name__ in str(payload)


def test_initialize_negotiates_a_supported_protocol_version() -> None:
    def never(tool: str, arguments: dict) -> tuple[bool, object]:
        raise AssertionError

    out = run_stdio(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2099-01-01"},
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            },
        ],
        never,
    )
    versions = {r["id"]: r["result"]["protocolVersion"] for r in out.replies}
    assert versions == {1: "2025-06-18", 2: "2024-11-05"}
