from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import cast

from starlette.applications import Starlette
from varde_runner.liveness import Liveness
from varde_runner.web.identities_route import create_identities_routes


async def _no_agent_rows(_supervisor):
    return []


async def _running_liveness(_session_id, pending_approvals=0):
    return Liveness("running", None)


def _rows_async(rows):
    async def agent_rows(supervisor):
        return rows(supervisor)

    return agent_rows


def request(app, method, path, payload=None):
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
                "headers": [
                    (b"host", b"localhost"),
                    (b"content-type", b"application/json"),
                ],
                "client": ("127.0.0.1", 1),
                "server": ("localhost", 80),
            },
            receive,
            send,
        )
        start = next(m for m in messages if m["type"] == "http.response.start")
        data = b"".join(
            m.get("body", b"") for m in messages if m["type"] == "http.response.body"
        )
        return start["status"], json.loads(data)

    return asyncio.run(dispatch())


def test_defaults_invalid_file_and_put_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    supervisor = SimpleNamespace(data_dir=tmp_path / "state")
    routes = create_identities_routes(lambda: supervisor)

    # The route module uses the shared agent-row projection; isolate profile behavior.
    import varde_runner.web.identities_route as module

    monkeypatch.setattr(module, "_agent_rows", _no_agent_rows)
    app = Starlette(routes=routes)
    status, body = request(app, "GET", "/api/identities")
    assert status == 200
    assert {item["id"] for item in body["identities"]} >= {"manager", "builder"}
    assert not (tmp_path / "identities").exists()
    (tmp_path / "identities").mkdir()
    (tmp_path / "identities" / "builder.toml").write_text("broken = [")
    status, body = request(app, "GET", "/api/identities")
    builder = next(item for item in body["identities"] if item["id"] == "builder")
    assert status == 200 and builder["error"] and builder["name"] == "Builder"
    status, body = request(
        app,
        "PUT",
        "/api/identities/builder",
        {"name": "", "label": "Builder", "description": "", "role": "builder"},
    )
    assert status == 400 and "name" in body["errors"] and "role" in body["errors"]
    status, body = request(app, "PUT", "/api/identities/nope", {})
    assert status == 404


def test_put_atomic_replace_failure_preserves_previous_file(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    supervisor = SimpleNamespace(data_dir=tmp_path / "state")
    app = Starlette(routes=create_identities_routes(lambda: supervisor))
    import varde_runner.web.identities_route as module

    monkeypatch.setattr(module, "_agent_rows", _no_agent_rows)
    target = tmp_path / "identities" / "builder.toml"
    target.parent.mkdir()
    target.write_text('name = "old"\n')
    original = target.read_text()

    def fail_replace(*args):
        raise OSError("simulated")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    status, _ = request(
        app,
        "PUT",
        "/api/identities/builder",
        {"name": "New", "label": "Build", "description": ""},
    )
    assert status == 500 and target.read_text() == original


def test_instances_include_all_and_profile_override(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    state = tmp_path / "state"
    state.mkdir()
    (state / "registry.json").write_text(
        json.dumps(
            {
                "bindings": {
                    "address": {
                        "address": "address",
                        "harness": "fake",
                        "adapter": "fake",
                        "session_id": "o1",
                        "role": "orchestrator",
                        "plan_id": "plan-17",
                    }
                }
            }
        )
    )
    supervisor = SimpleNamespace(data_dir=state)
    import varde_runner.web.identities_route as module

    monkeypatch.setattr(
        module,
        "_agent_rows",
        _rows_async(
            lambda _supervisor: [
                {
                    "session_id": "o1",
                    "agent_id": "agent-1",
                    "role": "orchestrator",
                    "lifecycle": "running",
                },
                {
                    "session_id": "b1",
                    "agent_id": "agent-2",
                    "role": "builder",
                    "lifecycle": "idle",
                },
            ]
        ),
    )
    app = Starlette(routes=create_identities_routes(lambda: supervisor))
    status, body = request(app, "GET", "/api/identities/builder/instances?include=all")
    assert status == 200 and body["instances"][0]["agent_id"] == "agent-2"
    status, body = request(app, "GET", "/api/identities")
    profiles = {item["id"]: item for item in body["identities"]}
    assert profiles["orchestrator"]["instances"][0]["label"] == "plan-17"
    assert profiles["builder"]["instances"] is None
    status, body = request(
        app,
        "PUT",
        "/api/identities/builder",
        {"name": "Build Crew", "label": "Builders", "description": "Builds things"},
    )
    assert status == 200 and body["name"] == "Build Crew"
    assert (tmp_path / "identities" / "builder.toml").exists()


def test_unknown_identity_file_and_non_toml_files(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    directory = tmp_path / "identities"
    directory.mkdir()
    (directory / "custom.toml").write_text('name = "Custom"')
    (directory / "notes.txt").write_text("ignore")
    (directory / ".builder.toml.backup").write_text("ignore")
    supervisor = SimpleNamespace(data_dir=tmp_path / "state")
    import varde_runner.web.identities_route as module

    monkeypatch.setattr(module, "_agent_rows", _no_agent_rows)
    app = Starlette(routes=create_identities_routes(lambda: supervisor))
    status, body = request(app, "GET", "/api/identities")
    custom = next(item for item in body["identities"] if item["id"] == "custom")
    assert status == 200 and custom["error"] == "unknown identity"
    assert custom["kind"] == "unknown"
    assert not any(
        item["id"] in {"notes", ".builder.toml"} for item in body["identities"]
    )


def test_put_returns_list_shape_and_get_reads_override(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    supervisor = SimpleNamespace(data_dir=tmp_path / "state")
    import varde_runner.web.identities_route as module

    monkeypatch.setattr(module, "_agent_rows", _no_agent_rows)
    app = Starlette(routes=create_identities_routes(lambda: supervisor))
    status, saved = request(
        app,
        "PUT",
        "/api/identities/builder",
        {"name": "Build Crew", "label": "Builders", "description": "Builds things"},
    )
    assert status == 200
    assert set(saved) == {
        "id",
        "name",
        "label",
        "description",
        "role",
        "kind",
        "count",
        "worst_state",
        "instances",
    }
    status, body = request(app, "GET", "/api/identities")
    builder = next(item for item in body["identities"] if item["id"] == "builder")
    assert status == 200 and builder == saved


def test_put_rejects_overlong_description_and_role_field(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    supervisor = SimpleNamespace(data_dir=tmp_path / "state")
    app = Starlette(routes=create_identities_routes(lambda: supervisor))
    status, body = request(
        app,
        "PUT",
        "/api/identities/builder",
        {
            "name": "Builder",
            "label": "Builder",
            "description": "x" * 281,
            "role": "builder",
        },
    )
    assert status == 400
    assert "description" in body["errors"] and "role" in body["errors"]


def test_instances_unknown_identity_is_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    supervisor = SimpleNamespace(data_dir=tmp_path / "state")
    app = Starlette(routes=create_identities_routes(lambda: supervisor))
    status, _ = request(app, "GET", "/api/identities/nope/instances")
    assert status == 404


def test_agent_rows_expose_session_id_for_registry_join():
    from varde_runner.supervisor import Supervisor
    from varde_runner.web.agents_route import _agent_rows

    supervisor = SimpleNamespace(
        approval_waits_for_mailbox=list,
        store=SimpleNamespace(
            sessions=lambda: [
                {
                    "id": "session-123",
                    "agent_id": "display-456",
                    "backend": "adapter",
                    "harness": "fake",
                    "role": "builder",
                    "workspace_id": "repo",
                    "lifecycle": "running",
                    "idle_status": None,
                }
            ]
        ),
        registry=SimpleNamespace(plugin_for_key=lambda _key: None),
        liveness=_running_liveness,
    )
    rows = asyncio.run(_agent_rows(cast("Supervisor", supervisor)))
    assert rows[0]["session_id"] == "session-123"


def test_directory_fsync_failure_keeps_successful_replace(tmp_path, monkeypatch):
    import os
    import stat

    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    supervisor = SimpleNamespace(data_dir=tmp_path / "state")
    app = Starlette(routes=create_identities_routes(lambda: supervisor))
    import varde_runner.web.identities_route as module

    monkeypatch.setattr(module, "_agent_rows", _no_agent_rows)
    original_fsync = os.fsync

    def fail_directory_fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("directory fsync unavailable")
        original_fsync(fd)

    monkeypatch.setattr(module.os, "fsync", fail_directory_fsync)
    status, _ = request(
        app,
        "PUT",
        "/api/identities/builder",
        {"name": "New", "label": "Build", "description": ""},
    )
    assert status == 200
    assert 'name = "New"' in (tmp_path / "identities" / "builder.toml").read_text()


def test_registry_bindings_accessor_returns_snapshot_by_session_id(tmp_path):
    from varde_runner.registry import SessionBinding, SessionRegistry

    registry = SessionRegistry(tmp_path / "registry.json")
    binding = SessionBinding(
        "address", "fake", "adapter", "session-1", "orchestrator", "plan-1"
    )
    registry.register(binding)
    assert registry.bindings_by_session_id() == {"session-1": binding}


def test_other_identity_does_not_expand_in_list_response(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    supervisor = SimpleNamespace(data_dir=tmp_path / "state")
    import varde_runner.web.identities_route as module

    monkeypatch.setattr(
        module,
        "_agent_rows",
        _rows_async(
            lambda _supervisor: [
                {
                    "session_id": "mail",
                    "agent_id": "mailman-1",
                    "role": "mailman",
                    "lifecycle": "running",
                }
            ]
        ),
    )
    app = Starlette(routes=create_identities_routes(lambda: supervisor))
    status, body = request(app, "GET", "/api/identities")
    other = next(item for item in body["identities"] if item["id"] == "other")
    assert status == 200 and other["count"] == 1 and other["instances"] is None


def test_bot_callers_see_only_their_own_instances(tmp_path, monkeypatch):
    from varde_runner.bot_tokens import BotIdentity

    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    state = tmp_path / "state"
    state.mkdir()
    rows = [
        {
            "session_id": "s1",
            "agent_id": "a1",
            "parent_id": None,
            "role": "builder",
            "launched_by": "bot:manager",
            "lifecycle": "idle",
        },
        {
            "session_id": "s2",
            "agent_id": "user-1",
            "parent_id": None,
            "role": "builder",
            "launched_by": "user",
            "lifecycle": "idle",
        },
    ]
    import varde_runner.web.identities_route as module

    monkeypatch.setattr(module, "_agent_rows", _rows_async(lambda _s: rows))
    inner = Starlette(
        routes=create_identities_routes(lambda: SimpleNamespace(data_dir=state))
    )

    def as_bot(actor):
        async def wrapped(scope, receive, send):
            scope["bot_identity"] = BotIdentity(actor, "s")
            await inner(scope, receive, send)

        return wrapped

    path = "/api/identities/builder/instances?include=all"
    _, body = request(as_bot("bot:manager"), "GET", path)
    assert [row["agent_id"] for row in body["instances"]] == ["a1"]
    _, body = request(as_bot("bot:manager/a1"), "GET", path)
    assert [row["agent_id"] for row in body["instances"]] == ["a1"]
    _, body = request(inner, "GET", path)
    assert len(body["instances"]) == 2
