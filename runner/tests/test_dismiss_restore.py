from test_web import app_request, setup_app
from varde_runner.web.threads_route import _plan_titles

OPEN = "m-43e3c0fe"
OTHER = "m-fda9bf2e"
MINE = {OPEN, OTHER}


def make_app(tmp_path, monkeypatch):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    cli.plan = {
        "plans": [{"id": "restore-plan", "status": "active", "assigned_to": "builder"}]
    }
    cli.extra_bindings = [{"address": "builder", "plan_id": "restore-plan"}]
    cli.messages = [
        {"id": msg_id, "from": "builder", "kind": "needs-user", "notes": None}
        for msg_id in (OPEN, OTHER)
    ]
    app.state.dashboard.snapshot_loaded_at = 0
    return app, cli, store


def get(app, path):
    return app_request(app, "GET", path).json()


def post(app, path):
    return app_request(app, "POST", path)


def open_ids(app):
    return {item["msg_id"] for item in get(app, "/api/mailbox")["open"]} & MINE


def test_dismiss_then_restore_round_trip(tmp_path, monkeypatch):
    app, _, store = make_app(tmp_path, monkeypatch)
    assert open_ids(app) == {OPEN, OTHER}

    dismissed = post(app, f"/api/mailbox/{OPEN}/dismiss")
    assert dismissed.status_code == 200
    assert dismissed.json() == {"dismissed": True, "msg_id": OPEN}
    mailbox = get(app, "/api/mailbox")
    assert open_ids(app) == {OTHER}
    assert [item["msg_id"] for item in mailbox["resolved"]] == [OPEN]
    assert mailbox["resolved"][0]["state"] == "dismissed"

    restored = post(app, f"/api/mailbox/{OPEN}/restore")
    assert restored.status_code == 200
    assert restored.json() == {"restored": True, "msg_id": OPEN}
    assert open_ids(app) == {OPEN, OTHER}
    assert get(app, "/api/mailbox")["resolved"] == []
    assert [(row["prior_state"], row["new_state"]) for row in store.audit_rows()] == [
        ("pending", "dismissed"),
        ("dismissed", "pending"),
    ]
    store.close()


def test_dismiss_does_not_ack_or_answer(tmp_path, monkeypatch):
    app, cli, store = make_app(tmp_path, monkeypatch)
    post(app, f"/api/mailbox/{OPEN}/dismiss")
    post(app, f"/api/mailbox/{OPEN}/restore")
    assert cli.acknowledged == []
    assert cli.sent == []
    assert store.db.execute("select count(*) from answers").fetchone()[0] == 0
    store.close()


def test_dismiss_and_restore_reject_wrong_state(tmp_path, monkeypatch):
    app, _, store = make_app(tmp_path, monkeypatch)
    assert post(app, f"/api/mailbox/{OPEN}/restore").status_code == 404
    assert post(app, "/api/mailbox/m-00000000/dismiss").status_code == 404
    post(app, f"/api/mailbox/{OPEN}/dismiss")
    assert post(app, f"/api/mailbox/{OPEN}/dismiss").status_code == 404
    store.close()


def test_bulk_dismiss_moves_every_item_to_resolved(tmp_path, monkeypatch):
    app, _, store = make_app(tmp_path, monkeypatch)
    for msg_id in (OPEN, OTHER):
        assert post(app, f"/api/mailbox/{msg_id}/dismiss").status_code == 200
    mailbox = get(app, "/api/mailbox")
    assert open_ids(app) == set()
    assert {item["msg_id"] for item in mailbox["resolved"]} == MINE
    store.close()


def test_threads_counts_agree_with_mailbox_open(tmp_path, monkeypatch):
    app, _, store = make_app(tmp_path, monkeypatch)

    def counts():
        opened = len(get(app, "/api/mailbox")["open"])
        threads = get(app, "/api/threads")
        return (
            sum(thread["open_count"] for thread in threads),
            sum(thread["stale_count"] for thread in threads),
            opened,
        )

    assert counts() == (2, 0, 2)
    post(app, f"/api/mailbox/{OPEN}/dismiss")
    assert counts() == (1, 0, 1)
    post(app, f"/api/mailbox/{OPEN}/restore")
    assert counts() == (2, 0, 2)
    store.close()


def test_plan_titles_come_from_plan_frontmatter(tmp_path):
    folder = tmp_path / "plans" / "lexical-rank"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_text("---\ntitle: Lexical ranking\nstatus: done\n---\n")
    assert _plan_titles(tmp_path) == {"lexical-rank": "Lexical ranking"}
