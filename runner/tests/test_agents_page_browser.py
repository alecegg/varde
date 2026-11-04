from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fakes.plugin import FakePlugin
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from test_agents_api import app_with_injected_registry
from varde_runner.config import Role, RoleConfig
from varde_runner.plugins import RunnerCapabilities
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.supervisor import Supervisor
from varde_runner.web.agent_watch import create_agent_watch_route
from varde_runner.web.app import UI_DIR

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not (UI_DIR / "index.html").is_file(), reason="runner UI is not built"
    ),
]


def run(coro):
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


@pytest.fixture
def agent_browser(browser_server, shared_browser_page, tmp_path, monkeypatch):
    page = shared_browser_page
    connect = sqlite3.connect
    monkeypatch.setattr(
        sqlite3,
        "connect",
        lambda *args, **kwargs: connect(*args, check_same_thread=False, **kwargs),
    )
    plugin = FakePlugin(
        RunnerCapabilities(resume=True, interrupt=True, respond=True, idle_status=True)
    )
    registry = PluginRegistry(["claude_cli", "codex_app_server"])
    registry.register("claude_cli", plugin)
    supervisor = Supervisor(tmp_path, registry)
    run(supervisor.start())
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        "varde_runner.agent_launch.load_config",
        lambda *_args: RoleConfig(
            {"builder": Role("claude_cli", "model", "medium", "auto", ())}, ()
        ),
    )
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path))

    async def get_supervisor():
        return supervisor

    app = app_with_injected_registry(registry, supervisor)
    watch_route = next(
        index
        for index, route in enumerate(app.routes)
        if getattr(route, "path", "").endswith("/watch")
    )
    app.routes[watch_route] = create_agent_watch_route(get_supervisor)

    async def workspaces(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "workspaces": [
                    {"id": str(workspace), "title": "Test workspace", "last_used": True}
                ]
            }
        )

    async def roles(request: Request) -> JSONResponse:
        return JSONResponse({"roles": {"builder": {"name": "builder"}}})

    async def settings(request: Request) -> JSONResponse:
        return JSONResponse({"app_icon": ""})

    async def instance_threads(request: Request) -> JSONResponse:
        agent_id = request.query_params.get("agent")
        threads = (
            []
            if not agent_id
            else [
                {
                    "thread_key": f"instance:{agent_id}",
                    "agent_id": agent_id,
                    "plan_id": None,
                    "role": "builder",
                    "label": "Browser builder",
                    "state": "idle",
                    "last_activity": None,
                }
            ]
        )
        return JSONResponse({"threads": threads})

    async def instance_thread_shell(request: Request) -> FileResponse:
        return FileResponse(UI_DIR / "spa-fallback.html")

    async def events(request: Request) -> Response:
        return Response("", media_type="text/event-stream")

    async def threads(request: Request) -> JSONResponse:
        return JSONResponse(mailbox_state["threads"])

    async def mailbox(request: Request) -> JSONResponse:
        return JSONResponse({"items": mailbox_state["items"]})

    async def mailbox_detail(request: Request) -> JSONResponse:
        item = next(
            (
                item
                for item in mailbox_state["items"]
                if item["msg_id"] == request.path_params["decision_id"]
            ),
            None,
        )
        return JSONResponse(item or {}, status_code=200 if item else 404)

    mailbox_state = {"threads": [], "items": []}

    from varde_runner.web.app import UI_DIR

    app.routes.extend(
        [
            Route("/agents", lambda request: FileResponse(UI_DIR / "index.html")),
            Route("/thread/{agent_id:str}", instance_thread_shell),
            Route("/plans", lambda request: FileResponse(UI_DIR / "index.html")),
            Route("/api/workspaces", workspaces),
            Route("/api/roles", roles),
            Route("/api/settings", settings),
            Route("/api/instance-threads", instance_threads),
            Route("/api/threads", threads),
            Route("/api/mailbox", mailbox),
            Route("/api/mailbox/{decision_id:str}", mailbox_detail),
            Route("/events", events),
            Mount("/_app", app=StaticFiles(directory=str(UI_DIR / "_app"))),
        ]
    )
    origin = browser_server(app)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/agents")
    yield page, origin, supervisor, plugin, workspace, mailbox_state
