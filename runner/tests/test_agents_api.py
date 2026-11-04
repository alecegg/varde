from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fakes.plugin import FakePlugin
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from varde_data.records.addresses import ReaderContext
from varde_runner.agent_launch import DisabledHarnessError
from varde_runner.clients import ClientRole
from varde_runner.config import Role, RoleConfig, default_config
from varde_runner.instance_cap import InstanceCapError
from varde_runner.plugins import RunnerCapabilities, SessionSpec
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.relay import RelayCLIProtocol, RelayWorker
from varde_runner.supervisor import SendOutcome, Supervisor
from varde_runner.waits import approval_wait_id
from varde_runner.web.agent_watch import create_agent_watch_route
from varde_runner.web.agents_route import agent_capabilities, create_agents_routes


def app_with_injected_registry(
    registry: PluginRegistry, supervisor: Supervisor
) -> Starlette:
    async def capabilities(request: Request) -> JSONResponse:
        return JSONResponse(agent_capabilities(registry))

    return Starlette(
        routes=[
            Route("/api/agents/capabilities", capabilities),
            create_agent_watch_route(lambda: supervisor),
            *create_agents_routes(lambda: supervisor),
        ]
    )


@pytest.fixture
def api(tmp_path, monkeypatch):
    config = replace(default_config(), stall_after_s=10)
    monkeypatch.setattr("varde_runner.supervisor.load_config", lambda *_: config)
    plugin = FakePlugin(
        RunnerCapabilities(resume=True, interrupt=True, respond=True, idle_status=True)
    )
    registry = PluginRegistry(["claude_cli", "codex_app_server"])
    registry.register("claude_cli", plugin)
    supervisor = Supervisor(tmp_path, registry)
    asyncio.run(supervisor.start())
    return app_with_injected_registry(registry, supervisor), supervisor, plugin


async def request(app, method: str, path: str, payload=None, query: str = ""):
    body = json.dumps(payload).encode() if payload is not None else b""
    messages = []
    received = False

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "root_path": "",
            "headers": [(b"host", b"127.0.0.1")],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 80),
        },
        receive,
        send,
    )
    start = messages[0]
    response_body = b"".join(item.get("body", b"") for item in messages[1:])
    return start["status"], json.loads(response_body) if response_body else {}


def start_agent(supervisor: Supervisor, tmp_path, harness: str = "claude_cli"):
    return asyncio.run(
        supervisor.start_session(
            SessionSpec(harness, "model", "workspace", str(tmp_path), "initial"),
            "builder",
        )
    )


def attach_writer(
    supervisor: Supervisor,
    agent_id: str,
    client: str = "client-a",
    role: ClientRole = ClientRole.WRITER,
):
    supervisor.clients.attach(agent_id, client, role)
    return client


def test_launch_statuses_and_capabilities(api, monkeypatch, tmp_path) -> None:
    app, supervisor, _ = api

    async def launch(sup, harness, workspace, role, prompt, address=None, **options):
        if harness == "codex_app_server":
            raise DisabledHarnessError("disabled")
        return await sup.start_session(
            SessionSpec("claude_cli", "model", workspace, str(tmp_path), prompt), role
        )

    monkeypatch.setattr("varde_runner.web.agents_route.launch_agent", launch)
    valid = {
        "harness": "claude_cli",
        "workspace": "workspace",
        "role": "builder",
        "prompt": "hi",
    }
    status, body = asyncio.run(request(app, "POST", "/api/agents", valid))
    assert status == 201 and "agent_id" in body
    assert (
        asyncio.run(
            request(
                app, "POST", "/api/agents", {**valid, "harness": "codex_app_server"}
            )
        )[0]
        == 409
    )
    assert asyncio.run(request(app, "POST", "/api/agents", {}))[0] == 400
    assert (
        asyncio.run(request(app, "POST", "/api/agents", {**valid, "prompt": ""}))[0]
        == 400
    )
    status, body = asyncio.run(request(app, "GET", "/api/agents/capabilities"))
    assert status == 200 and body["disabled"] == ["codex_app_server"]
    assert supervisor.store.sessions()


def test_launch_instance_cap_returns_structured_conflict(api, monkeypatch):
    app, _, _ = api

    async def refuse(*_args, **_options):
        raise InstanceCapError(8, 8)

    monkeypatch.setattr("varde_runner.web.agents_route.launch_agent", refuse)
    status, body = asyncio.run(
        request(
            app,
            "POST",
            "/api/agents",
            {
                "harness": "claude_cli",
                "workspace": "workspace",
                "role": "builder",
                "prompt": "start",
            },
        )
    )

    assert status == 409
    assert body == {"error": "instance_cap", "live": 8, "max": 8}


def test_launch_address_routes_relay_wake_and_stop_unbinds(
    api, monkeypatch, tmp_path
) -> None:
    app, supervisor, plugin = api
    role = Role("claude_cli", "model", "medium", "auto", ())
    monkeypatch.setattr(
        "varde_runner.agent_launch.load_config",
        lambda *_args: RoleConfig({"builder": role}, ()),
    )
    working = tmp_path / "working"
    working.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    payload = {
        "harness": "claude_cli",
        "workspace": str(workspace),
        "role": "builder",
        "prompt": "do the work",
        "address": {"slot": "orchestrator-2", "plan": "plan-1"},
    }

    status, body = asyncio.run(request(app, "POST", "/api/agents", payload))

    assert status == 201
    agent_id = body["agent_id"]
    assert plugin.started[-1].prompt.startswith("[varde-address: orchestrator-2 vt1.")
    assert plugin.started[-1].prompt.endswith("\ndo the work")
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.records.messages import NewMessage
    from varde_data.relay import RelayService

    now = datetime.now(UTC) + timedelta(minutes=5)
    data = open_data(working, load_data_config())
    binding = data.addresses.current_binding("orchestrator-2")
    assert binding is not None
    assert binding.extra["wake_context"] == {
        "agent_id": agent_id,
        "harness": "claude-cli",
        "session_id": "remote-1",
        "cwd": str(workspace),
    }
    data.messages.append(
        NewMessage(
            "sender",
            "orchestrator-2",
            "info",
            "wake me",
            ts=(now - timedelta(minutes=3)).isoformat(),
        )
    )
    mailman_marker = data.addresses.issue("mailman", now=now, issuer="test")
    assert data.addresses.redeem(
        mailman_marker,
        "mailman-session",
        "codex",
        ReaderContext(cwd=str(working)),
        now=now,
    )
    mailman_token = data.addresses.current_token("mailman")
    assert mailman_token is not None
    action = RelayService(data.addresses, data.messages, now=lambda: now).once(
        mailman_token, now
    )["actions"][0]

    class RelayCommand:
        async def renew(self, action_id: str) -> dict[str, str]:
            return {"status": "renewed"}

    relay = RelayWorker(cast("RelayCLIProtocol", RelayCommand()), supervisor)

    outcome = asyncio.run(relay.deliver(action))

    assert outcome == ("pushed", "successful-send")
    assert plugin.sent[-1] == ("remote-1", action["prompt"])
    assert action["wake"]["agent_id"] == agent_id
    assert action["wake"]["harness"] == "claude-cli"
    binding_row = supervisor.store.get_address_binding(agent_id)
    assert binding_row is not None
    assert binding_row["working_dir"] == str(working)
    assert (
        open_data(workspace, load_data_config()).addresses.current_binding(
            "orchestrator-2"
        )
        is None
    )

    asyncio.run(supervisor.stop(agent_id, "system:dashboard"))
    assert data.addresses.current_binding("orchestrator-2") is None

    archive_payload = {
        **payload,
        "address": {"slot": "orchestrator-3"},
        "prompt": "finish and archive",
    }
    status, archive_body = asyncio.run(
        request(app, "POST", "/api/agents", archive_payload)
    )
    assert status == 201
    archived_id = archive_body["agent_id"]
    supervisor.store.update_session(archived_id, status="completed")
    asyncio.run(supervisor.archive(archived_id, "system:dashboard"))
    assert data.addresses.current_binding("orchestrator-3") is None


def test_list_includes_rows_and_pending_requests(api, tmp_path) -> None:
    app, supervisor, _ = api
    ref = start_agent(supervisor, tmp_path)
    supervisor.store.create_wait(
        approval_wait_id(ref.session_id, "request-1"),
        ref.session_id,
        "approval",
        payload={"request_id": "request-1", "summary": "Permission requested"},
    )
    status, rows = asyncio.run(request(app, "GET", "/api/agents"))
    assert status == 200
    assert rows[0]["agent_id"] == ref.session_id
    stored = supervisor.store.get_session(ref.session_id)
    assert rows[0]["idle_status"] == stored["idle_status"]
    assert rows[0]["capabilities"]["respond"] is True
    assert rows[0]["liveness"] == "waiting"
    assert rows[0]["liveness_reason"] is None
    assert rows[0]["pending_requests"] == [
        {
            "request_id": "request-1",
            "kind": "approval",
            "summary": "Permission requested",
        }
    ]


def test_list_reports_stalled_without_changing_idle_status(api, tmp_path) -> None:
    app, supervisor, plugin = api
    ref = start_agent(supervisor, tmp_path)
    remote_ref = supervisor._refs[ref.session_id]
    plugin.status[remote_ref.session_id] = "running"
    supervisor.store.append_event(ref.session_id, "status", {"status": "running"})
    old_event = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    supervisor.store.connection.execute(
        "UPDATE events SET created_at = ? WHERE session_id = ?",
        (old_event, ref.session_id),
    )
    supervisor.store.connection.commit()
    stored_idle_status = supervisor.store.get_session(ref.session_id)["idle_status"]
    assert supervisor._stall_after_seconds == 10
    assert asyncio.run(supervisor.liveness(ref.session_id)).reason == "silent"

    status, rows = asyncio.run(request(app, "GET", "/api/agents"))

    assert status == 200
    row = next(item for item in rows if item["agent_id"] == ref.session_id)
    assert row["liveness"] == "stalled"
    assert row["liveness_reason"] == "silent"
    assert row["idle_status"] == stored_idle_status


def test_prompt_interrupt_respond_and_security(api, tmp_path) -> None:
    app, supervisor, plugin = api
    ref = start_agent(supervisor, tmp_path)
    agent_id = ref.session_id
    client = attach_writer(supervisor, agent_id)
    base = f"/api/agents/{agent_id}"
    assert (
        asyncio.run(
            request(app, "POST", f"{base}/prompt", {"text": "hello", "client": client})
        )[0]
        == 200
    )
    assert plugin.sent[-1][1] == "hello"
    assert (
        asyncio.run(request(app, "POST", f"{base}/interrupt", {"client": client}))[0]
        == 200
    )
    assert asyncio.run(
        request(
            app,
            "POST",
            f"{base}/respond",
            {"request_id": "stale-id", "decision": "approve", "client": client},
        )
    ) == (409, {"result": "stale"})
    for system_id in ("system:", "system:dashboard", "system:relay", "system:delivery"):
        assert (
            asyncio.run(
                request(
                    app, "POST", f"{base}/prompt", {"text": "x", "client": system_id}
                )
            )[0]
            == 400
        )
    assert (
        asyncio.run(
            request(app, "POST", f"{base}/prompt", {"text": "x", "client": "unknown"})
        )[0]
        == 409
    )
    observer = attach_writer(supervisor, agent_id, "observer-a", ClientRole.OBSERVER)
    assert (
        asyncio.run(
            request(app, "POST", f"{base}/prompt", {"text": "x", "client": observer})
        )[0]
        == 409
    )
    assert (
        asyncio.run(
            request(
                app,
                "POST",
                "/api/agents/missing/respond",
                {"request_id": "r", "decision": "approve", "client": client},
            )
        )[0]
        == 404
    )
    assert (
        asyncio.run(request(app, "POST", f"{base}/prompt", {"client": client}))[0]
        == 400
    )
    assert asyncio.run(request(app, "POST", f"{base}/interrupt", {}))[0] == 400
    assert (
        asyncio.run(request(app, "POST", f"{base}/respond", {"client": client}))[0]
        == 400
    )


def test_lifecycle_dispatch_is_closed_and_watch_remains_reachable(
    api, tmp_path
) -> None:
    app, supervisor, _ = api
    ref = start_agent(supervisor, tmp_path)
    base = f"/api/agents/{ref.session_id}"
    client = attach_writer(supervisor, ref.session_id)
    payload = {"client": client}
    assert asyncio.run(request(app, "POST", f"{base}/stop", payload))[0] == 200
    assert asyncio.run(request(app, "POST", f"{base}/stop", payload))[0] == 200
    assert asyncio.run(request(app, "POST", f"{base}/archive", payload))[0] == 200
    assert asyncio.run(request(app, "POST", f"{base}/archive", payload))[0] == 200
    assert asyncio.run(request(app, "POST", f"{base}/resume", payload))[0] == 409
    assert asyncio.run(request(app, "POST", f"{base}/stop"))[0] == 400
    for invalid in ("", "system:", "system:dashboard"):
        assert (
            asyncio.run(request(app, "POST", f"{base}/stop", {"client": invalid}))[0]
            == 400
        )
    assert asyncio.run(request(app, "POST", f"{base}/foo"))[0] == 404
    assert asyncio.run(request(app, "POST", f"{base}/watch"))[0] == 404

    watch = next(route for route in app.routes if route.path.endswith("/watch"))
    action_route = next(route for route in app.routes if route.path.endswith("/prompt"))
    fallback = next(
        route for route in app.routes if route.path.endswith("{action:str}")
    )
    assert app.routes.index(watch) < app.routes.index(action_route)
    assert app.routes.index(watch) < app.routes.index(fallback)


def test_archive_running_and_resume_unsupported(api, tmp_path) -> None:
    app, supervisor, _ = api
    running = start_agent(supervisor, tmp_path)
    client = attach_writer(supervisor, running.session_id)
    payload = {"client": client}
    assert (
        asyncio.run(
            request(app, "POST", f"/api/agents/{running.session_id}/archive", payload)
        )[0]
        == 409
    )
    assert (
        asyncio.run(
            request(app, "POST", f"/api/agents/{running.session_id}/resume", payload)
        )[0]
        == 200
    )
    unsupported = FakePlugin(RunnerCapabilities())
    supervisor.registry.register("unsupported", unsupported)
    other = start_agent(supervisor, tmp_path, "unsupported")
    other_client = attach_writer(supervisor, other.session_id)
    assert (
        asyncio.run(
            request(
                app,
                "POST",
                f"/api/agents/{other.session_id}/resume",
                {"client": other_client},
            )
        )[0]
        == 501
    )


def test_interrupt_failure_and_unsupported_and_respond_unsupported(
    api, tmp_path, monkeypatch
) -> None:
    app, supervisor, _plugin = api
    ref = start_agent(supervisor, tmp_path)
    client = attach_writer(supervisor, ref.session_id)
    original_interrupt = supervisor.interrupt

    async def failed_interrupt(agent_id, client_id):
        return SendOutcome.FAILED_INTERRUPT

    monkeypatch.setattr(supervisor, "interrupt", failed_interrupt)
    assert (
        asyncio.run(
            request(
                app,
                "POST",
                f"/api/agents/{ref.session_id}/interrupt",
                {"client": client},
            )
        )[0]
        == 409
    )
    monkeypatch.setattr(supervisor, "interrupt", original_interrupt)
    unsupported = FakePlugin(RunnerCapabilities())
    supervisor.registry.register("unsupported", unsupported)
    other = start_agent(supervisor, tmp_path, "unsupported")
    other_client = attach_writer(supervisor, other.session_id)
    assert (
        asyncio.run(
            request(
                app,
                "POST",
                f"/api/agents/{other.session_id}/interrupt",
                {"client": other_client},
            )
        )[0]
        == 501
    )
    assert (
        asyncio.run(
            request(
                app,
                "POST",
                f"/api/agents/{other.session_id}/respond",
                {"request_id": "r", "decision": "approve", "client": other_client},
            )
        )[0]
        == 501
    )


def test_write_adapter_errors_are_generic(api, tmp_path, monkeypatch) -> None:
    app, supervisor, _ = api
    ref = start_agent(supervisor, tmp_path)
    client = attach_writer(supervisor, ref.session_id)

    async def raw_adapter_error(*args, **kwargs):
        raise RuntimeError("/secret/provider/path")

    monkeypatch.setattr(supervisor, "send", raw_adapter_error)
    status, body = asyncio.run(
        request(
            app,
            "POST",
            f"/api/agents/{ref.session_id}/prompt",
            {"text": "x", "client": client},
        )
    )
    assert status == 409 and body == {"error": "agent action failed"}


def test_respond_success_and_archived_resume_conflict(api, tmp_path) -> None:
    app, supervisor, plugin = api
    ref = start_agent(supervisor, tmp_path)
    client = attach_writer(supervisor, ref.session_id)
    request_id = "permission-1"
    supervisor.store.create_wait(
        approval_wait_id(ref.session_id, request_id),
        ref.session_id,
        "approval",
        payload={"request_id": request_id},
    )
    status, body = asyncio.run(
        request(
            app,
            "POST",
            f"/api/agents/{ref.session_id}/respond",
            {"request_id": request_id, "decision": "approve", "client": client},
        )
    )
    assert (status, body) == (200, {"result": "responded"})
    assert plugin.responses == [(request_id, "approve")]
    asyncio.run(supervisor.stop(ref.session_id, "system:dashboard"))
    asyncio.run(supervisor.archive(ref.session_id, "system:dashboard"))
    assert (
        asyncio.run(
            request(
                app,
                "POST",
                f"/api/agents/{ref.session_id}/resume",
                {"client": client},
            )
        )[0]
        == 409
    )


def test_launch_passes_optional_harness_mode_and_parent(
    api, monkeypatch, tmp_path
) -> None:
    app, _, _ = api
    seen = {}

    async def launch(sup, harness, workspace, role, prompt, address=None, **options):
        seen.update(harness=harness, options=options)
        return await sup.start_session(
            SessionSpec("claude_cli", "m", workspace, str(tmp_path), prompt), role
        )

    monkeypatch.setattr("varde_runner.web.agents_route.launch_agent", launch)
    body = {"workspace": "w", "role": "builder", "prompt": "hi"}
    status, _ = asyncio.run(request(app, "POST", "/api/agents", body))
    assert status == 201
    assert seen == {
        "harness": None,
        "options": {"mode": None, "parent_id": None, "launched_by": None},
    }

    status, _ = asyncio.run(
        request(
            app,
            "POST",
            "/api/agents",
            {**body, "mode": "full-access", "parent_id": "p1"},
        )
    )
    assert status == 201
    assert seen["options"] == {
        "mode": "full-access",
        "parent_id": "p1",
        "launched_by": None,
    }
    for bad in ({"mode": ""}, {"parent_id": 3}, {"harness": ""}):
        assert (
            asyncio.run(request(app, "POST", "/api/agents", {**body, **bad}))[0] == 400
        )


def test_list_returns_parent_id_and_filters_by_parent(api, tmp_path) -> None:
    app, supervisor, _ = api
    child = start_agent(supervisor, tmp_path)
    start_agent(supervisor, tmp_path)
    supervisor.store.update_session(child.session_id, parent_id="p1")

    status, rows = asyncio.run(request(app, "GET", "/api/agents"))
    assert status == 200 and len(rows) == 2
    assert {row["parent_id"] for row in rows} == {"p1", None}
    status, rows = asyncio.run(request(app, "GET", "/api/agents", query="parent=p1"))
    assert [row["session_id"] for row in rows] == [child.session_id]
    assert all("liveness" in row for row in rows)


def test_mode_route_changes_mode_and_maps_errors(api, tmp_path) -> None:
    app, supervisor, plugin = api
    ref = start_agent(supervisor, tmp_path)
    client = attach_writer(supervisor, ref.session_id)
    path = f"/api/agents/{ref.session_id}/mode"

    status, body = asyncio.run(
        request(app, "POST", path, {"client": client, "mode": "full-access"})
    )
    assert (status, body) == (200, {"mode": "full-access"})
    assert plugin.resumed_settings[-1].mode_id == "full-access"

    client = attach_writer(supervisor, ref.session_id, "client-b")
    assert asyncio.run(request(app, "POST", path, {"client": client}))[0] == 400
    status, body = asyncio.run(
        request(app, "POST", path, {"client": client, "mode": "bogus"})
    )
    assert status == 400 and "bogus" in body["error"]
    assert (
        asyncio.run(request(app, "POST", path, {"client": "nobody", "mode": "auto"}))[0]
        == 409
    )
    missing = "/api/agents/missing/mode"
    assert (
        asyncio.run(request(app, "POST", missing, {"client": "c", "mode": "auto"}))[0]
        == 404
    )
