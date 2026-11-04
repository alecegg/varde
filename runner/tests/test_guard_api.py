import asyncio
import json
from types import SimpleNamespace

from starlette.applications import Starlette
from varde_runner.store import SessionStore
from varde_runner.web.guard_route import guard_routes


def _request(app, path, method="GET", body=b""):
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
                "client": ("127.0.0.1", 1234),
                "server": ("localhost", 80),
            },
            receive,
            send,
        )
        start = next(item for item in messages if item["type"] == "http.response.start")
        data = b"".join(
            item.get("body", b"")
            for item in messages
            if item["type"] == "http.response.body"
        )
        return start["status"], json.loads(data)

    return asyncio.run(dispatch())


def _app(store):
    async def getter():
        return SimpleNamespace(store=store)

    app = Starlette(routes=guard_routes())
    app.state.dashboard = SimpleNamespace(supervisor_getter=getter)
    return app


def _record(
    store, index, *, verdict="approve", prompt="run git status", reason="known safe"
):
    store.record_guard_verdict(
        "session",
        str(index),
        "command_prefix:git",
        "tool",
        prompt,
        verdict,
        reason,
        verdict == "escalate",
    )


def test_guard_api_reads_all_approvals_and_preserves_revoked_patterns(tmp_path):
    store = SessionStore(tmp_path)
    app = _app(store)
    try:
        for index in range(501):
            _record(store, index)
        store.revoke_guard_pattern("command_prefix:old")

        status, response = _request(app, "/api/guard/approvals")

        assert status == 200
        patterns = {item["request_key"]: item for item in response["approvals"]}
        assert patterns["command_prefix:git"]["count"] == 501
        assert patterns["command_prefix:old"] == {
            "request_key": "command_prefix:old",
            "count": 0,
            "last_ts": "",
            "revoked": True,
        }
    finally:
        store.close()


def test_guard_api_revoke_persists_and_unrevoke_removes_revocation(tmp_path):
    store = SessionStore(tmp_path)
    app = _app(store)
    try:
        _record(store, 1)
        status, _ = _request(
            app, "/api/guard/revoke", "POST", b'{"request_key":"command_prefix:git"}'
        )
        assert status == 200
        store.close()
        store = SessionStore(tmp_path)
        app = _app(store)
        assert "command_prefix:git" in store.revoked_guard_patterns()

        status, _ = _request(
            app, "/api/guard/unrevoke", "POST", b'{"request_key":"command_prefix:git"}'
        )
        assert status == 200
        assert "command_prefix:git" not in store.revoked_guard_patterns()
    finally:
        store.close()


def test_guard_api_paginates_and_redacts_verdict_fields(tmp_path):
    store = SessionStore(tmp_path)
    app = _app(store)
    try:
        _record(store, 1, prompt="GITHUB_TOKEN=abc123", reason="--token abc-secret")
        _record(store, 2, verdict="escalate")
        status, first = _request(app, "/api/guard/verdicts?limit=1")
        assert status == 200
        assert first["verdicts"][0]["request_key"] == "command_prefix:git"
        assert set(first["verdicts"][0]) == {
            "id",
            "ts",
            "request_key",
            "request_kind",
            "prompt",
            "verdict",
            "reason",
            "escalated",
        }
        assert "abc123" not in first["verdicts"][0]["prompt"]
        assert "abc-secret" not in first["verdicts"][0]["reason"]
        before = first["verdicts"][0]["id"]
        status, previous = _request(app, f"/api/guard/verdicts?limit=1&before={before}")
        assert status == 200
        assert previous["verdicts"][0]["id"] < before
    finally:
        store.close()


def test_guard_api_rejects_invalid_pagination_and_revocation_bodies(tmp_path):
    store = SessionStore(tmp_path)
    app = _app(store)
    try:
        for query in ("limit=0", "limit=501", "before=0", "before=abc"):
            assert _request(app, f"/api/guard/verdicts?{query}")[0] == 400
        for body in (b"not-json", b"[]", b'{"request_key":""}'):
            assert _request(app, "/api/guard/revoke", "POST", body)[0] == 400
            assert _request(app, "/api/guard/unrevoke", "POST", body)[0] == 400
    finally:
        store.close()


def test_guard_api_is_mounted_in_real_app(tmp_path, monkeypatch):
    from test_roles_web import EmptyCLI
    from test_web import app_request
    from varde_runner.web import app as web_app
    from varde_runner.web import create_app

    store = SessionStore(tmp_path / "store")

    class FakeSupervisor:
        def __init__(self, data_dir, plugins):
            self.store = store

        async def start(self):
            pass

        async def shutdown(self):
            pass

    monkeypatch.setattr(web_app, "Supervisor", FakeSupervisor)
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())
    try:
        _record(store, 1)
        assert app_request(app, "GET", "/api/guard/verdicts").status_code == 200
        assert app_request(app, "GET", "/api/guard/approvals").status_code == 200
        revoke = app_request(
            app,
            "POST",
            "/api/guard/revoke",
            content=b'{"request_key":"command_prefix:git"}',
            headers={"content-type": "application/json"},
        )
        assert revoke.status_code == 200
        approvals = app_request(app, "GET", "/api/guard/approvals").json()
        revoked = {a["request_key"]: a["revoked"] for a in approvals["approvals"]}
        assert revoked["command_prefix:git"] is True
    finally:
        store.close()
