from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from starlette.requests import Request
from varde_runner.bot_route_policy import READ, iter_route_keys, policy_for
from varde_runner.config import ROLE_NAMES
from varde_runner.user_credential import UserCredential
from varde_runner.web.app import create_app
from varde_runner.web.role_queue_route import create_role_queue_routes


def request(path: str, params: dict[str, str] | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": b"",
        "path_params": params or {},
    }
    return Request(scope)


def test_home_sorts_role_summaries(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "varde_runner.web.role_queue_route.config_dir", lambda: tmp_path
    )

    async def agent_rows(_supervisor):
        return []

    monkeypatch.setattr("varde_runner.web.role_queue_route._agent_rows", agent_rows)
    supervisor = SimpleNamespace(data_dir=tmp_path)
    dashboard = SimpleNamespace(
        queue_inputs=lambda: (
            {"plans": [{"id": "plan-1", "assigned_to": "builder", "status": "active"}]},
            [],
        )
    )
    route = create_role_queue_routes(dashboard, lambda: supervisor)[0]
    response = asyncio.run(route.endpoint(request("/api/home")))

    assert response.status_code == 200
    roles = json.loads(response.body)["roles"]
    assert [role["state"] for role in roles] == sorted(
        (role["state"] for role in roles),
        key=lambda state: {"needs_you": 0, "running": 1, "idle": 2, "done": 3}[state],
    )
    assert set(ROLE_NAMES) <= {role["role"] for role in roles}


def test_unknown_role_returns_404(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "varde_runner.web.role_queue_route.config_dir", lambda: tmp_path
    )

    async def agent_rows(_supervisor):
        return []

    monkeypatch.setattr("varde_runner.web.role_queue_route._agent_rows", agent_rows)
    supervisor = SimpleNamespace(data_dir=tmp_path)
    dashboard = SimpleNamespace(queue_inputs=lambda: ({"plans": []}, []))
    route = create_role_queue_routes(dashboard, lambda: supervisor)[1]
    response = asyncio.run(
        route.endpoint(request("/api/queue/roles/not-a-role", {"role": "not-a-role"}))
    )

    assert response.status_code == 404
    assert json.loads(response.body) == {"error": "unknown role"}


def test_the_three_queue_read_routes_are_served_and_classified(tmp_path):
    app = create_app(
        data_dir=tmp_path / "data",
        bound_port=8765,
        user_credential=UserCredential(tmp_path / "user-credential.json"),
    )
    served = set(iter_route_keys(app.routes))
    for path in ("/api/home", "/api/queue/roles", "/api/queue/roles/{role:str}"):
        assert ("GET", path) in served
        assert policy_for("GET", path) is READ
