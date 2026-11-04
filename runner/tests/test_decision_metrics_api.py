import asyncio
import json
from types import SimpleNamespace

from varde_runner.web import create_app


class _Store:
    def __init__(self):
        self.rows = [
            {
                "created_at": "2026-10-19T20:00:00+00:00",
                "role": "builder",
                "response": "approve",
                "time_to_answer_s": 5,
                "request_key": "command_prefix:git",
            },
            {
                "created_at": "2026-10-20T10:00:00+00:00",
                "role": "builder",
                "response": "approve",
                "time_to_answer_s": 7,
                "request_key": "command_prefix:git",
            },
            {
                "created_at": "2026-10-21T10:00:00+00:00",
                "role": "builder",
                "response": "approve",
                "time_to_answer_s": 9,
                "request_key": "command_prefix:git",
            },
        ]
        self.since_args = []

    def decision_events(self, since=None):
        self.since_args.append(since)
        return [row for row in self.rows if since is None or row["created_at"] >= since]


class _Response:
    def __init__(self, status, body):
        self.status_code = status
        self.content = body

    def json(self):
        return json.loads(self.content)


def _asgi_request(app, path, host="127.0.0.1:8765"):
    async def dispatch():
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

        raw_path, _, query = path.partition("?")
        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": raw_path,
                "raw_path": raw_path.encode(),
                "query_string": query.encode(),
                "root_path": "",
                "headers": [(b"host", host.encode())],
                "client": ("127.0.0.1", 1234),
                "server": ("127.0.0.1", 8765),
            },
            receive,
            send,
        )
        start = next(
            message for message in messages if message["type"] == "http.response.start"
        )
        body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        return _Response(start["status"], body)

    return asyncio.run(dispatch())


def _app(tmp_path):
    app = create_app(data_dir=tmp_path, bound_port=8765)
    store = _Store()

    async def get_supervisor():
        return SimpleNamespace(store=store)

    app.state.dashboard.supervisor_getter = get_supervisor
    return app, store


def test_metrics_route_is_registered_and_candidates_use_unfiltered_history(tmp_path):
    app, store = _app(tmp_path)
    response = _asgi_request(
        app,
        "/api/decision-metrics?group_by=role&since=2026-10-20T00%3A00%3A00%2B02%3A00",
    )
    assert response.status_code == 200
    assert response.json() == {
        "groups": [
            {
                "group": "builder",
                "count": 2,
                "responses": {"approve": 2, "deny": 0, "ask_more": 0, "expired": 0},
                "approve_rate": 1.0,
                "deny_rate": 0.0,
                "expired_rate": 0.0,
                "median_time_to_answer_s": 8.0,
            }
        ],
        "candidates": ["command_prefix:git"],
    }
    assert store.since_args == [None]


def test_metrics_route_supports_day_and_week_groups_and_default_role(tmp_path):
    app, _ = _app(tmp_path)
    day = _asgi_request(app, "/api/decision-metrics?group_by=day")
    week = _asgi_request(app, "/api/decision-metrics?group_by=week")
    default = _asgi_request(app, "/api/decision-metrics")
    assert [item["group"] for item in day.json()["groups"]] == [
        "2026-10-19",
        "2026-10-20",
        "2026-10-21",
    ]
    assert [item["group"] for item in week.json()["groups"]] == ["2026-10-19"]
    assert default.json()["groups"][0]["group"] == "builder"


def test_metrics_route_rejects_invalid_group_and_since_and_non_loopback(tmp_path):
    app, _ = _app(tmp_path)
    invalid_group = _asgi_request(app, "/api/decision-metrics?group_by=unknown")
    invalid_since = _asgi_request(app, "/api/decision-metrics?since=garbage")
    denied = _asgi_request(app, "/api/decision-metrics", host="example.test:8765")
    assert invalid_group.status_code == 400
    assert invalid_group.json() == {"error": "invalid group_by"}
    assert invalid_since.status_code == 400
    assert invalid_since.json() == {"error": "invalid since"}
    assert denied.status_code == 403


def test_metrics_route_returns_503_when_supervisor_getter_is_unavailable(tmp_path):
    app = create_app(data_dir=tmp_path, bound_port=8765)
    app.state.dashboard.supervisor_getter = None
    response = _asgi_request(app, "/api/decision-metrics")
    assert response.status_code == 503
    assert response.json() == {"error": "supervisor unavailable"}
