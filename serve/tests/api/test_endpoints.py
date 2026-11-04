"""Endpoints against a real daemon: reads, writes, gates, config allowlist."""

from collections.abc import Callable

import pytest
from conftest import Served

Factory = Callable[..., Served]
EDIT = "[serve]\nallow_edit = true\n"


def make_plan(served: Served) -> None:
    plan = served.working / "plans" / "p1"
    (plan / "tasks").mkdir(parents=True)
    (plan / "plan.md").write_text(
        "---\ntype: plan\ntitle: Plan One\nstatus: backlog\n---\n"
        "\n## Problem\n\nSomething.\n"
    )
    (plan / "tasks" / "t1.md").write_text("---\ntype: task\nstatus: todo\n---\nbody\n")


def test_plan_reads(served_factory: Factory) -> None:
    served = served_factory()
    make_plan(served)
    status, body = served.request("GET", "/api/plans")
    assert status == 200
    assert "Plan One" in str(body)
    status, detail = served.request("GET", "/api/plans/p1")
    assert status == 200
    assert detail["tasks"][0]["id"] == "t1"  # type: ignore[index]
    assert served.request("GET", "/api/plans/p1/tasks/t1")[0] == 200
    assert served.request("GET", "/api/plans/nope")[0] == 404
    assert served.request("GET", "/api/plans/p1/tasks/..%2Fplan")[0] == 404


def test_reads_need_a_token(served_factory: Factory) -> None:
    served = served_factory()
    bare = {"Host": f"127.0.0.1:{served.port}"}
    for path in ("/api/plans", "/api/queue", "/api/config", "/api/docs", "/pages/x.md"):
        assert served.request("GET", path, headers=bare)[0] == 401


def test_queue_not_set_up_is_409(served_factory: Factory) -> None:
    served = served_factory(EDIT)
    status, error = served.request("GET", "/api/queue")
    assert (status, error["error"]["code"]) == (409, "queue_unavailable")  # type: ignore[index]


def test_docs_comment_reply_and_decision_scopes(served_factory: Factory) -> None:
    served = served_factory(EDIT)
    (served.working / "notes").mkdir()
    (served.working / "notes" / "a.md").write_text("# A\n\nText.\n")
    assert served.request("GET", "/api/docs")[1]["docs"] == [{"path": "notes/a.md"}]  # type: ignore[index]
    status, comment = served.request(
        "POST",
        "/api/docs/notes/a.md/comments",
        {"anchor": "top", "text": "hi"},
        scope="mcp",
    )
    assert status == 201
    cid = comment["id"]  # type: ignore[index]
    status, _ = served.request(
        "POST",
        f"/api/docs/notes/a.md/comments/{cid}/replies",
        {"text": "ok"},
        scope="mcp",
    )
    assert status == 201
    _, doc = served.request("GET", "/api/docs/notes/a.md")
    assert doc["comments"][0]["replies"][0]["text"] == "ok"  # type: ignore[index]
    assert served.request("GET", "/pages/notes/a.md")[0] == 200
    # Decision answers are human-only: mcp scope is refused, human reaches the library.
    decide = "/api/docs/notes/a.md/decisions/d1"
    assert served.request("POST", decide, {"answer": "approve"}, scope="mcp")[0] == 403
    assert (
        served.request("POST", decide, {"answer": "approve"})[0] == 400
    )  # no such block
    assert served.request("GET", "/api/docs/../../etc/passwd")[0] == 404
    assert (
        served.request("POST", "/api/docs/notes/a.md/comments", {"kind": "decision"})[0]
        == 400
    )


def test_agent_writes_need_allow_edit(served_factory: Factory) -> None:
    served = served_factory()
    status, error = served.request("POST", "/api/friction", {"text": "x"}, scope="mcp")
    assert status == 403
    assert error["error"]["code"] == "edit_disabled"  # type: ignore[index]
    assert (
        served.request("POST", "/api/mail", {"to": "a", "kind": "info", "text": "t"})[0]
        == 403
    )


def test_config_allowlist(served_factory: Factory) -> None:
    served = served_factory(EDIT)
    keys = {r["key"] for r in served.request("GET", "/api/config")[1]["keys"]}  # type: ignore[index]
    assert "orchestration.stall_minutes" in keys
    assert not any(k.startswith(("serve.", "runner.")) for k in keys)
    ok, body = served.request(
        "PUT", "/api/config/orchestration.stall_minutes", {"value": 90}
    )
    assert ok == 200
    assert body["value"] == 90  # type: ignore[index]
    for key in ("serve.allow_edit", "runner.enabled", "serve.bind"):
        assert served.request("PUT", f"/api/config/{key}", {"value": True})[0] == 400
    assert (
        served.request(
            "PUT", "/api/config/orchestration.stall_minutes", {"value": 1}, scope="mcp"
        )[0]
        == 403
    )


def test_search_requires_query_and_valid_domain(served_factory: Factory) -> None:
    served = served_factory()
    make_plan(served)
    assert served.request("GET", "/api/search")[0] == 400
    assert served.request("GET", "/api/search?q=x&domain=nope")[0] == 400
    status, body = served.request("GET", "/api/search?q=plan%20one&domain=plans")
    assert status == 200
    assert body["results"]["plans"][0]["id"] == "p1"  # type: ignore[index]


def test_static_root_and_missing_static(served_factory: Factory) -> None:
    served = served_factory()
    assert served.request("GET", "/")[0] == 200
    assert (
        served.request(
            "GET", "/static/app.js", headers={"Host": f"127.0.0.1:{served.port}"}
        )[0]
        == 404
    )


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_unknown_write_routes_fail_closed(served_factory: Factory, method: str) -> None:
    served = served_factory(EDIT)
    assert served.request(method, "/api/plans", {}, scope="mcp")[0] == 403


def test_friction_add_and_list(served_factory: Factory) -> None:
    served = served_factory(EDIT)
    status, added = served.request(
        "POST",
        "/api/friction",
        {"text": "tool hung twice", "tags": ["serve"]},
        scope="mcp",
    )
    assert status == 201, added
    status, listed = served.request("GET", "/api/friction?tag=serve")
    assert status == 200
    assert listed["total"] == 1  # type: ignore[index]
    assert (
        served.request("POST", "/api/friction", {"text": "  "}, scope="mcp")[0] == 400
    )
    assert served.request("GET", "/api/friction?status=bogus")[0] == 400


def test_mail_send_and_read(served_factory: Factory) -> None:
    served = served_factory(EDIT)
    status, sent = served.request(
        "POST",
        "/api/mail",
        {"to": "main", "kind": "info", "text": "hello"},
        scope="mcp",
    )
    assert status == 201, sent
    _, mail = served.request("GET", "/api/mail")
    assert [m["text"] for m in mail["messages"]] == ["hello"]  # type: ignore[index]
    assert served.request("POST", "/api/mail", {"to": "main", "kind": "info"})[0] == 400


def test_queue_reorder_is_not_wired_yet(served_factory: Factory) -> None:
    served = served_factory(EDIT)
    status, error = served.request("POST", "/api/queue/reorder", {"ids": ["a"]})
    assert (status, error["error"]["code"]) == (501, "reorder_not_wired")  # type: ignore[index]
    mcp_status, _ = served.request("POST", "/api/queue/reorder", {}, scope="mcp")
    assert mcp_status == 403


def test_odd_and_hidden_doc_paths_are_404(served_factory: Factory) -> None:
    served = served_factory(EDIT)
    for hidden in (".git", "archive", "node_modules"):
        (served.working / hidden).mkdir()
        (served.working / hidden / "x.md").write_text("# hidden\n")
        assert served.request("GET", f"/api/docs/{hidden}/x.md")[0] == 404
        assert served.request("GET", f"/pages/{hidden}/x.md")[0] == 404
    assert served.request("GET", "/api/docs/a%00.md")[0] == 404
    assert served.request("GET", "/pages/a%00.md")[0] == 404


def test_event_poll_checks_origin_and_returns_events_published_during_wait(
    served_factory: Factory,
) -> None:
    import threading
    import time

    served = served_factory(EDIT)
    (served.working / "notes").mkdir()
    (served.working / "notes" / "a.md").write_text("# A\n\nText.\n")
    headers = served.headers(Origin="http://evil.example")
    assert served.request("GET", "/api/events/poll", headers=headers)[0] == 403
    time.sleep(0.5)  # let the watchers prime before the first poll

    def comment_soon() -> None:
        time.sleep(0.5)
        served.request(
            "POST",
            "/api/docs/notes/a.md/comments",
            {"anchor": "top", "text": "late"},
            scope="mcp",
        )

    writer = threading.Thread(target=comment_soon)
    writer.start()
    status, body = served.request("GET", "/api/events/poll?wait_s=5")  # no cursor
    writer.join()
    assert status == 200
    assert [e["kind"] for e in body["events"]] == ["doc.comment"]  # type: ignore[index]
    assert body["cursor"] == body["events"][-1]["id"]  # type: ignore[index]
