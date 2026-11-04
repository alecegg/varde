import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

import pytest
from varde_runner import agent_cli


class _Stub(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, conflicts: int) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.conflicts = conflicts
        self.conflict_text = "write client is not authorized"
        self.watch_query = ""
        self.posts: list[tuple[str, dict]] = []
        self.watch_open_during_post: list[bool] = []
        self.watch_closed = threading.Event()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    @property
    def stub(self) -> _Stub:
        return cast("_Stub", self.server)

    def do_GET(self) -> None:
        self.stub.watch_query = self.path
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b": open\n\n")
        self.wfile.flush()
        try:
            while self.rfile.read(1):
                pass
        except OSError:
            pass
        finally:
            self.stub.watch_closed.set()

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        self.stub.posts.append((self.path, body))
        self.stub.watch_open_during_post.append(not self.stub.watch_closed.is_set())
        if len(self.stub.posts) <= self.stub.conflicts:
            self._reply(409, {"error": self.stub.conflict_text})
            return
        self._reply(200, {"outcome": "sent"})

    def _reply(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def stub():
    def start(conflicts: int = 0):
        server = _Stub(conflicts)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server

    servers: list[_Stub] = []
    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def test_payload_and_url_shapes():
    assert agent_cli.write_payload("prompt", "c1", "hi") == {
        "client": "c1",
        "text": "hi",
    }
    assert agent_cli.write_payload("interrupt", "c1", None) == {"client": "c1"}
    assert (
        agent_cli.write_url("a/b", "prompt", 9)
        == "http://127.0.0.1:9/api/agents/a%2Fb/prompt"
    )


def test_prompt_posts_writer_client_while_watch_stream_is_held(stub):
    server = stub()

    result = agent_cli.run("prompt", "agent-1", "say ok", server.server_port)

    assert result == {"outcome": "sent"}
    assert "role=writer" in server.watch_query
    client = server.watch_query.split("client=")[1].split("&")[0]
    assert server.posts == [
        ("/api/agents/agent-1/prompt", {"client": client, "text": "say ok"})
    ]
    assert server.watch_open_during_post == [True]
    assert server.watch_closed.wait(2)


def test_interrupt_retries_until_the_writer_attach_lands(stub):
    server = stub(conflicts=2)

    result = agent_cli.run("interrupt", "agent-1", None, server.server_port)

    assert result == {"outcome": "sent"}
    assert [path for path, _ in server.posts] == ["/api/agents/agent-1/interrupt"] * 3


def test_other_conflicts_fail_without_retry(stub):
    server = stub(conflicts=1000)
    server.conflict_text = "agent action failed"

    with pytest.raises(SystemExit, match="agent action failed"):
        agent_cli.run("prompt", "agent-1", "x", server.server_port)

    assert len(server.posts) == 1


def test_persistent_conflict_exits_with_the_error(stub, monkeypatch):
    monkeypatch.setattr(agent_cli, "ATTACH_RETRY_SECONDS", 0.3)
    server = stub(conflicts=1000)

    with pytest.raises(SystemExit, match="HTTP 409"):
        agent_cli.run("prompt", "agent-1", "x", server.server_port)


def test_prompt_without_text_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        agent_cli.main(["prompt", "agent-1"])

    assert exc.value.code == 2


class _ApiHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def _reply(self, status: int, payload) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self.server.requests.append(("GET", self.path, None))  # type: ignore[attr-defined]
        self._reply(200, [{"session_id": "a1", "liveness": "live", "parent_id": "p"}])

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        self.server.requests.append(("POST", self.path, body))  # type: ignore[attr-defined]
        if body.get("role") == "capped":
            self._reply(409, {"error": "instance_cap", "live": 8, "max": 8})
            return
        self._reply(201, {"agent_id": "new-agent"})


@pytest.fixture
def api_stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ApiHandler)
    server.requests = []  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


def run_main(capsys, *argv: str) -> str:
    agent_cli.main(list(argv))
    return capsys.readouterr().out


def test_launch_posts_the_contract_and_prints_id_and_address(api_stub, capsys):
    port = str(api_stub.server_port)
    out = run_main(
        capsys,
        "launch", "--port", port, "--role", "builder", "--workspace", "w1",
        "--prompt", "do it", "--mode", "full-access", "--slot", "b1",
        "--plan", "plan-x", "--parent", "p1",
    )  # fmt: skip

    assert json.loads(out) == {"id": "new-agent", "address": "b1"}
    assert api_stub.requests == [
        (
            "POST",
            "/api/agents",
            {
                "role": "builder",
                "workspace": "w1",
                "prompt": "do it",
                "mode": "full-access",
                "parent_id": "p1",
                "address": {"slot": "b1", "plan": "plan-x"},
            },
        )
    ]


def test_launch_parent_defaults_to_the_caller_environment(
    api_stub, capsys, monkeypatch
):
    monkeypatch.setenv("VARDE_AGENT_ID", "env-agent")
    monkeypatch.setattr(
        "sys.argv", ["x"]
    )  # argparse default is read when the parser is built
    run_main(
        capsys, "launch", "--port", str(api_stub.server_port),
        "--role", "builder", "--workspace", "w", "--prompt", "p",
    )  # fmt: skip
    assert api_stub.requests[0][2]["parent_id"] == "env-agent"
    assert "harness" not in api_stub.requests[0][2]


def test_launch_reads_the_prompt_from_stdin(api_stub, capsys, monkeypatch):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("from stdin"))
    run_main(
        capsys, "launch", "--port", str(api_stub.server_port),
        "--role", "builder", "--workspace", "w", "--prompt", "-",
    )  # fmt: skip
    assert api_stub.requests[0][2]["prompt"] == "from stdin"


def test_launch_instance_cap_exits_2_with_the_cap_message(api_stub, capsys):
    with pytest.raises(SystemExit) as exc:
        agent_cli.main(
            ["launch", "--port", str(api_stub.server_port), "--role", "capped",
             "--workspace", "w", "--prompt", "p"]
        )  # fmt: skip
    assert exc.value.code == 2
    assert "instance cap reached: 8 of 8" in capsys.readouterr().err


def test_launch_plan_requires_slot():
    with pytest.raises(SystemExit) as exc:
        agent_cli.main(
            [
                "launch",
                "--role",
                "r",
                "--workspace",
                "w",
                "--prompt",
                "p",
                "--plan",
                "x",
            ]
        )
    assert exc.value.code == 2


def test_list_filters_by_parent(api_stub, capsys):
    out = run_main(capsys, "list", "--port", str(api_stub.server_port), "--parent", "p")
    assert json.loads(out)[0]["parent_id"] == "p"
    assert api_stub.requests == [("GET", "/api/agents?parent=p", None)]


@pytest.mark.parametrize("action", ["stop", "archive"])
def test_stop_and_archive_use_the_writer_pattern(stub, capsys, action):
    server = stub()
    run_main(capsys, action, "agent-1", "--port", str(server.server_port))
    client = server.watch_query.split("client=")[1].split("&")[0]
    assert server.posts == [(f"/api/agents/agent-1/{action}", {"client": client})]


def test_mode_posts_the_new_mode(stub, capsys):
    server = stub()
    run_main(
        capsys, "mode", "agent-1", "full-access", "--port", str(server.server_port)
    )
    client = server.watch_query.split("client=")[1].split("&")[0]
    assert server.posts == [
        ("/api/agents/agent-1/mode", {"client": client, "mode": "full-access"})
    ]
