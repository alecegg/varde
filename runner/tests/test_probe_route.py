import asyncio
from types import SimpleNamespace

from starlette.requests import Request
from varde_runner.web.probe_route import probe_route


def test_probe_route_uses_only_workspace_cwds_off_loop(monkeypatch, tmp_path):
    class Registry:
        def harnesses(self):
            return {"one", "two"}

        async def list_workspaces(self, harness):
            return [{"cwd": str(tmp_path / harness)}]

    app = SimpleNamespace(state=SimpleNamespace(registry=Registry()))
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/probe",
            "headers": [],
            "app": app,
        }
    )
    calls = []

    def fake_probe(paths, timeout_s):
        calls.append((paths, timeout_s))
        return dict.fromkeys(paths, "ok")

    async def fake_to_thread(func, *args):
        return func(*args)

    monkeypatch.setattr("varde_runner.web.probe_route.probe_paths", fake_probe)
    monkeypatch.setattr(
        "varde_runner.web.probe_route.asyncio.to_thread", fake_to_thread
    )
    response = asyncio.run(probe_route(request))
    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] == sorted([str(tmp_path / "one"), str(tmp_path / "two")])
    assert "clean probe does not rule out other causes" in bytes(response.body).decode()
