from __future__ import annotations

import asyncio
import json
import os
import subprocess

from starlette.applications import Starlette
from test_web import app_request
from varde_runner.config import KNOWN_HARNESSES, default_toml
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSettings
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.supervisor import Supervisor
from varde_runner.web.agents_route import create_agents_routes
from varde_runner.web.newitem import create_newitem_routes
from varde_runner.web.workspaces import create_workspaces_routes
from varde_runner.workitems import WorkItemStore
from varde_runner.workspaces_service import WorkspaceError, WorkspacesService


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True)  # noqa: S603, S607


class FakeService:
    def __init__(self):
        self.removals = []

    async def list(self):
        return [
            {
                "id": "/native",
                "title": "repo / native",
                "cwd": "/native",
                "repo": "/repo",
                "kind": "worktree",
                "branch": "worktree/native",
                "head": "abc",
                "last_used": False,
            },
            {
                "id": "/repo",
                "title": "repo",
                "cwd": "/repo",
                "repo": "/repo",
                "kind": "repo",
                "branch": "main",
                "head": "def",
                "last_used": False,
            },
        ]

    async def create(self, repo, worktree_id, **kwargs):
        if repo != "/repo":
            raise WorkspaceError(404, "repo is not configured")
        if worktree_id == "exists":
            raise WorkspaceError(409, "worktree path or branch already exists")
        if worktree_id == "bad":
            raise WorkspaceError(422, "invalid worktree id")
        return {
            "id": "/native",
            "path": "/native",
            "branch": f"worktree/{worktree_id}",
            "base": "abc",
            "created": True,
        }

    async def remove(self, repo, worktree_id, **kwargs):
        self.removals.append((repo, worktree_id, kwargs))
        if worktree_id in {"dirty", "unmerged", "live", "inside", "admin"}:
            raise WorkspaceError(409, f"{worktree_id} removal refused")
        return {
            "removed": True,
            "branch": f"worktree/{worktree_id}",
            "ignored_removed": [],
        }


class FakePlugin:
    async def list_workspaces(self):
        return [
            {"id": "plugin", "title": "Plugin", "cwd": "/plugin"},
            {"id": "duplicate", "title": "Duplicate", "cwd": "/native"},
            {"id": "duplicate-two", "title": "Duplicate Two", "cwd": "/native"},
        ]


def registry():
    result = PluginRegistry()
    result.register("fake", FakePlugin())
    return result


def test_workspace_routes_create_and_remove_statuses(tmp_path):
    service = FakeService()
    store = WorkItemStore(tmp_path)
    app = Starlette(routes=create_workspaces_routes(registry, store, service))

    def request(method, body=None, path="/api/workspaces"):
        return app_request(
            app,
            method,
            path,
            content=json.dumps(body or {}).encode(),
            headers={"content-type": "application/json"},
        )

    assert request("POST", {"repo": "/repo", "id": "fresh"}).status_code == 201
    assert request("POST", {"repo": "/missing", "id": "fresh"}).status_code == 404
    assert request("POST", {"repo": "/repo", "id": "exists"}).status_code == 409
    assert request("POST", {"repo": "/repo", "id": "bad"}).status_code == 422
    for refusal in ("dirty", "unmerged", "live", "inside", "admin"):
        assert (
            request(
                "DELETE",
                path=f"/api/workspaces?repo=%2Frepo&id={refusal}&caller=%2Frepo",
            ).status_code
            == 409
        )
    assert (
        request(
            "DELETE", path="/api/workspaces?repo=%2Frepo&id=clean&caller=%2Frepo"
        ).status_code
        == 200
    )
    store.close()


def test_workspace_list_merges_native_first_and_deduplicates_cwd(tmp_path):
    store = WorkItemStore(tmp_path)
    app = Starlette(routes=create_workspaces_routes(registry, store, FakeService()))
    response = app_request(app, "GET", "/api/workspaces")
    assert response.status_code == 200
    rows = response.json()["workspaces"]
    assert [row["cwd"] for row in rows] == ["/native", "/repo", "/plugin"]
    assert rows[0]["kind"] == "worktree"
    assert rows[0]["branch"] == "worktree/native"
    assert rows[0]["repo"] == "/repo"
    assert {"id", "title", "cwd", "last_used"} <= rows[0].keys()
    store.close()


class FailingService:
    async def list(self):
        raise RuntimeError("native source unavailable")


class FailingPlugin:
    async def list_workspaces(self):
        raise RuntimeError("plugin source unavailable")


def test_workspace_list_returns_503_when_all_sources_fail(tmp_path):
    failed_registry = PluginRegistry()
    failed_registry.register("fake", FailingPlugin())
    store = WorkItemStore(tmp_path)
    app = Starlette(routes=create_workspaces_routes(lambda: failed_registry, store))

    response = app_request(app, "GET", "/api/workspaces")

    assert response.status_code == 503
    store.close()


def test_workspace_list_returns_plugin_entries_when_native_source_fails(tmp_path):
    store = WorkItemStore(tmp_path)
    app = Starlette(routes=create_workspaces_routes(registry, store, FailingService()))

    response = app_request(app, "GET", "/api/workspaces")

    assert response.status_code == 200
    assert [row["cwd"] for row in response.json()["workspaces"]] == [
        "/plugin",
        "/native",
        "/native",
    ]
    store.close()


def test_workspace_list_without_service_preserves_plugin_duplicates(tmp_path):
    store = WorkItemStore(tmp_path)
    app = Starlette(routes=create_workspaces_routes(registry, store))

    response = app_request(app, "GET", "/api/workspaces")

    assert response.status_code == 200
    assert [row["cwd"] for row in response.json()["workspaces"]] == [
        "/plugin",
        "/native",
        "/native",
    ]
    store.close()


def test_workspace_mutations_without_service_return_404(tmp_path):
    store = WorkItemStore(tmp_path)
    app = Starlette(routes=create_workspaces_routes(registry, store))

    created = app_request(
        app,
        "POST",
        "/api/workspaces",
        content=b"{}",
        headers={"content-type": "application/json"},
    )
    removed = app_request(app, "DELETE", "/api/workspaces?repo=%2Frepo&id=x")

    assert created.status_code == 404
    assert removed.status_code == 404
    store.close()


def test_workspace_create_rejects_bad_json(tmp_path):
    store = WorkItemStore(tmp_path)
    app = Starlette(routes=create_workspaces_routes(registry, store, FakeService()))

    response = app_request(
        app,
        "POST",
        "/api/workspaces",
        content=b"{",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    store.close()


def test_workspace_remove_parses_discard_and_passes_query_values(tmp_path):
    service = FakeService()
    store = WorkItemStore(tmp_path)
    app = Starlette(routes=create_workspaces_routes(registry, store, service))

    invalid = app_request(
        app,
        "DELETE",
        "/api/workspaces?repo=%2Frepo&id=clean&discard=sometimes",
    )
    discarded = app_request(
        app,
        "DELETE",
        "/api/workspaces?repo=%2Frepo&id=discarded&caller=%2Fcaller&discard=true",
    )
    regular = app_request(
        app,
        "DELETE",
        "/api/workspaces?repo=%2Frepo&id=regular&caller=%2Fcaller&discard=false",
    )

    assert invalid.status_code == 422
    assert discarded.status_code == 200
    assert regular.status_code == 200
    assert service.removals == [
        ("/repo", "discarded", {"caller": "/caller", "discard": True}),
        ("/repo", "regular", {"caller": "/caller", "discard": False}),
    ]
    store.close()


def test_submit_accepts_native_workspace_with_plugin_registry_present(tmp_path):
    store = WorkItemStore(tmp_path)
    app = Starlette(
        routes=create_newitem_routes(tmp_path, store, registry, FakeService())
    )
    app.state.work_item_start = lambda *_: "planner-session"
    response = app_request(
        app,
        "POST",
        "/api/work-items",
        content=json.dumps(
            {"text": "Plan", "idempotency_key": "native", "workspace_id": "/native"}
        ).encode(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 200
    assert store.list()[0].project == "/native"
    store.close()


class LaunchPlugin:
    capabilities = RunnerCapabilities()

    def __init__(self):
        self.spec = None

    def session_settings(self, model):
        return SessionSettings(model.model, model.reasoning_effort, model.mode)

    async def start(self, spec):
        self.spec = spec
        return SessionRef(spec.provider, "fake-session")

    async def stop(self, ref):
        pass

    async def events(self, ref):
        await asyncio.Event().wait()
        yield

    async def close(self):
        pass


def test_api_created_workspace_launches_and_upserts_store_row(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "tracked").write_text("initial")
    _git(repo, "add", "tracked")
    _git(repo, "commit", "-qm", "initial")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "runner.toml").write_text(default_toml())
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(config_dir))
    plugin = LaunchPlugin()
    registry = PluginRegistry((*KNOWN_HARNESSES, "fake"))
    registry.register("codex-app-server", plugin)
    supervisor = Supervisor(tmp_path / "sessions", registry)

    async def get_store():
        return supervisor.store

    service = WorkspacesService([repo], env=os.environ.copy(), get_store=get_store)
    app = Starlette(
        routes=[
            *create_workspaces_routes(
                lambda: registry, WorkItemStore(tmp_path / "items"), service
            ),
            *create_agents_routes(lambda: supervisor),
        ]
    )
    created = app_request(
        app,
        "POST",
        "/api/workspaces",
        content=json.dumps({"repo": str(repo), "id": "launch"}).encode(),
        headers={"content-type": "application/json"},
    )
    assert created.status_code == 201
    path = created.json()["path"]
    launched = app_request(
        app,
        "POST",
        "/api/agents",
        content=json.dumps(
            {
                "harness": "codex-app-server",
                "workspace": path,
                "role": "builder",
                "prompt": "go",
            }
        ).encode(),
        headers={"content-type": "application/json"},
    )
    assert launched.status_code == 201
    assert plugin.spec is not None
    assert plugin.spec.cwd == path
    workspace = supervisor.store.get_workspace(path)
    assert workspace is not None
    assert workspace["repo_root"] == str(repo)
    assert workspace["cwd"] == path
    for task in tuple(supervisor._event_tasks):
        task.cancel()
    supervisor.store.connection.close()
