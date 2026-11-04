from __future__ import annotations

import asyncio
import json

import pytest
from test_web import app_request
from varde_runner.plugins.paseo import PaseoPlugin
from varde_runner.web import create_app
from varde_runner.web.workspaces import validate_project
from varde_runner.workitems import WorkItemStore


def test_list_workspaces_shows_last_used(tmp_path, monkeypatch):
    class Plugin:
        async def list_workspaces(self):
            return [
                {"id": "one", "title": "One", "cwd": "/work/one"},
                {"id": "two", "title": "Two", "cwd": "/work/two"},
            ]

    monkeypatch.setattr(PaseoPlugin, "from_environment", Plugin)
    app = create_app(data_dir=tmp_path / "data")
    store = WorkItemStore(tmp_path / "data")
    store.create("old", "old", "one")
    store.create("new", "new", "two")

    response = app_request(app, "GET", "/api/workspaces")

    assert response.status_code == 200
    assert response.json() == {
        "workspaces": [
            {"id": "one", "title": "One", "cwd": "/work/one", "last_used": False},
            {"id": "two", "title": "Two", "cwd": "/work/two", "last_used": True},
        ]
    }


def test_submit_validates_workspace_or_existing_directory(tmp_path, monkeypatch):
    class Plugin:
        async def list_workspaces(self):
            return [{"id": "listed", "title": "Listed", "cwd": "/work/listed"}]

    monkeypatch.setattr(PaseoPlugin, "from_environment", Plugin)
    app = create_app(data_dir=tmp_path / "data")
    app.state.work_item_start = lambda *_: "session"

    def submit(key: str, **fields: str):
        return app_request(
            app,
            "POST",
            "/api/work-items",
            content=json.dumps(
                {"text": "Plan", "idempotency_key": key, **fields}
            ).encode(),
            headers={"content-type": "application/json"},
        )

    invalid = submit("invalid", project="unknown")
    listed = submit("listed", workspace_id="listed")
    directory = submit("directory", project=str(tmp_path))

    assert invalid.status_code == 400
    assert listed.status_code == 200
    assert directory.status_code == 200
    assert [item.project for item in WorkItemStore(tmp_path / "data").list()] == [
        "listed",
        str(tmp_path),
    ]


def test_validate_project_accepts_selected_project_without_plugin():
    result = asyncio.run(validate_project("varde-py", None, lambda: None))

    assert result == "varde-py"


def test_validate_project_tolerates_workspace_listing_runtime_failure():
    class Plugin:
        async def list_workspaces(self):
            raise RuntimeError("Paseo unavailable")

    result = asyncio.run(validate_project("project-id", None, Plugin))

    assert result == "project-id"


def test_validate_project_fails_open_before_native_lookup_when_plugin_fails():
    class Plugin:
        async def list_workspaces(self):
            raise RuntimeError("Paseo unavailable")

    class Service:
        async def list(self):
            raise AssertionError("native lookup should not run after plugin failure")

    result = asyncio.run(
        validate_project("project-id", None, Plugin, service=Service())
    )

    assert result == "project-id"


def test_validate_project_does_not_hide_programming_errors():
    class Plugin:
        async def list_workspaces(self):
            raise ValueError("bug")

    with pytest.raises(ValueError, match="bug"):
        asyncio.run(validate_project("project-id", None, Plugin))
