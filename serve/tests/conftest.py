"""Shared helpers: launch a real daemon subprocess and talk HTTP to it."""

import contextlib
import http.client
import json
import os
import signal
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from varde_serve.daemon.lifecycle import ensure_daemon, spawn_daemon
from varde_serve.daemon.state import DaemonInfo, read_info
from varde_serve.daemon.tokens import Tokens, ensure_tokens, state_dir


class Served:
    def __init__(self, config_dir: Path, working: Path) -> None:
        self.config_dir, self.working = config_dir, working
        self.tokens: Tokens = ensure_tokens(config_dir)
        code = (
            "import sys\n"
            "from pathlib import Path\n"
            "from varde_serve.daemon.lifecycle import run_daemon\n"
            "from varde_serve.daemon.wiring import Project, wire\n"
            "cfg, working = Path(sys.argv[1]), Path(sys.argv[2])\n"
            "project = Project(cfg, working, working)\n"
            "def configure(ctx):\n"
            "    ctx.poll_s = 0.2\n"
            "    ctx.keepalive_s = 0.5\n"
            "    wire(ctx, project)\n"
            "raise SystemExit(run_daemon(cfg, 'test', configure=configure))\n"
        )
        argv = (sys.executable, "-c", code, str(config_dir), str(working))
        self.info: DaemonInfo = ensure_daemon(config_dir, lambda: spawn_daemon(argv))

    @property
    def port(self) -> int:
        return self.info.port

    def headers(self, scope: str = "human", **extra: str) -> dict[str, str]:
        token = self.tokens.human if scope == "human" else self.tokens.mcp
        return {
            "Host": f"127.0.0.1:{self.port}",
            "Authorization": f"Bearer {token}",
            **extra,
        }

    def request(
        self,
        method: str,
        path: str,
        body: object = None,
        headers: dict[str, str] | None = None,
        scope: str = "human",
    ) -> tuple[int, object]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        merged = headers if headers is not None else self.headers(scope)
        connection.request(
            method, path, json.dumps(body) if body is not None else None, merged
        )
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        try:
            return response.status, json.loads(raw)
        except ValueError:
            return response.status, raw


@pytest.fixture
def served_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., Served]]:
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "learn"))
    made: list[Served] = []

    def make(config_text: str = "") -> Served:
        config_dir = tmp_path / "cfg"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "config.toml").write_text(config_text)
        working = tmp_path / "working"
        (working / "plans").mkdir(parents=True, exist_ok=True)
        served = Served(config_dir, working)
        made.append(served)
        return served

    yield make
    for served in made:
        info = read_info(state_dir(served.config_dir))
        if info is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(info.pid, signal.SIGKILL)
