from __future__ import annotations

import asyncio
import contextlib
import json
import multiprocessing
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from starlette.requests import Request
from starlette.routing import Route
from varde_runner.config import default_toml
from varde_runner.web import create_app
from varde_runner.web.app import _plan_rows


class _CLI:
    def __init__(
        self,
        working_dir: Path,
        *,
        plan_status=None,
        fail=False,
        delay: float = 0,
    ):
        self.cwd = working_dir
        self.env = {"VARDE_WORKING_DIR": str(working_dir)}
        self.status = plan_status
        self.fail = fail
        self.delay = delay

    def read_messages(self):
        return []

    def read_plan(self):
        return {"plans": [], "events": []}

    def read_plan_status(self):
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("plan status unavailable")
        return self.status if self.status is not None else {"plans": []}

    def read_plan_watch(self):
        time.sleep(self.delay)
        return {"events": []}

    def read_assigned_plans(self):
        time.sleep(self.delay)
        return []

    def read_address_bindings(self):
        time.sleep(self.delay)
        return []

    def read_message_status(self):
        return {"messages": []}

    def read_concluded_addresses(self):
        return []

    def send(self, **_kwargs):
        return {"id": "sent"}


class _Supervisor:
    def approval_waits_for_mailbox(self):
        return []


def _http_get(app, path: str) -> tuple[int, dict]:
    async def dispatch():
        parsed_path = urlsplit(path)
        messages = []
        received = False

        async def receive():
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        with contextlib.suppress(Exception):
            await app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "GET",
                    "scheme": "http",
                    "host": "localhost:8000",
                    "path": parsed_path.path,
                    "raw_path": parsed_path.path.encode(),
                    "query_string": parsed_path.query.encode(),
                    "root_path": "",
                    "headers": [(b"host", b"localhost:8000")],
                    "client": ("127.0.0.1", 1234),
                    "server": ("127.0.0.1", 8000),
                },
                receive,
                send,
            )
        start = next(
            (item for item in messages if item["type"] == "http.response.start"),
            None,
        )
        body = b"".join(
            item.get("body", b"")
            for item in messages
            if item["type"] == "http.response.body"
        )
        return (start["status"] if start else 500), json.loads(body or b"{}")

    return asyncio.run(dispatch())


@pytest.mark.parametrize("unavailable", ["none", "raises"])
@pytest.mark.parametrize("endpoint", ["/api/orchestrators", "/api/queue"])
def test_unavailable_plan_status_degrades_without_failing(
    tmp_path, monkeypatch, unavailable, endpoint
):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path / "runner-config"))
    (tmp_path / "runner-config").mkdir()
    (tmp_path / "runner-config" / "runner.toml").write_text(default_toml())
    cli = _CLI(tmp_path, fail=unavailable == "raises")
    if unavailable == "none":
        cli.read_plan_status = lambda: None
    app = create_app(data_dir=tmp_path / "dashboard", cli=cli, agents=list)

    async def get_supervisor():
        return _Supervisor()

    app.state.dashboard.supervisor_getter = get_supervisor

    status, payload = _http_get(app, endpoint)
    degraded_status, degraded = _http_get(app, "/api/degraded")

    assert status == 200
    assert isinstance(payload, dict)
    assert degraded_status == 200
    assert "plan_status" in degraded["sources"]
    if endpoint == "/api/orchestrators":
        assert payload["plans"] == []


def test_plan_rows_tolerates_missing_status_and_watch():
    plans, _, _ = _plan_rows(None, None, [], object(), [], [])
    assert plans == []


def _concurrent_request_probe(tmp_path: str) -> None:
    root = Path(tmp_path)
    config_dir = root / "config"
    config_dir.mkdir()
    (config_dir / "runner.toml").write_text(default_toml(), encoding="utf-8")
    os.environ["VARDE_RUNNER_CONFIG_DIR"] = str(config_dir)
    app = create_app(
        data_dir=root / "dashboard",
        cli=_CLI(root, plan_status={"plans": []}, delay=0.03),
        agents=list,
    )

    def route(path: str):
        endpoint = next(
            route.endpoint
            for route in app.routes
            if isinstance(route, Route) and route.path == path
        )

        def make_request():
            return Request(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "GET",
                    "scheme": "http",
                    "path": path,
                    "raw_path": path.encode(),
                    "query_string": b"",
                    "headers": [],
                    "server": ("127.0.0.1", 8000),
                    "client": ("127.0.0.1", 1234),
                    "app": app,
                }
            )

        async def run():
            response = await endpoint(make_request())
            return response.status_code

        return run

    async def check():
        calls = [route("/api/queue") for _ in range(12)] + [
            route("/api/orchestrators") for _ in range(12)
        ]
        statuses = await asyncio.wait_for(
            asyncio.gather(*(call() for call in calls)), timeout=2
        )
        assert statuses == [200] * 24

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    executor = ThreadPoolExecutor(max_workers=4)
    loop.set_default_executor(executor)
    try:
        loop.run_until_complete(check())
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
    except TimeoutError:
        os._exit(23)
    finally:
        loop.close()


def test_concurrent_cold_queue_and_orchestrator_requests_do_not_starve_executor(
    tmp_path,
):
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_concurrent_request_probe, args=(str(tmp_path),))
    process.start()
    process.join(timeout=5)
    if process.is_alive():
        process.terminate()
        process.join(timeout=2)
    assert process.exitcode == 0
