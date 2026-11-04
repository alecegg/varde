from varde_data.open_decisions import OPEN_DECISION_KINDS, open_decision_items


def test_open_decisions_filters_acknowledged_unbound_and_replied() -> None:
    items = [
        {
            "msg_id": "open",
            "sender": "active",
            "kind": "needs-user",
            "ts": "1",
            "state": "pending",
        },
        {
            "msg_id": "ack",
            "sender": "active",
            "kind": "needs-user",
            "ts": "1",
            "state": "pending",
        },
        {
            "msg_id": "unbound",
            "sender": "other",
            "kind": "needs-user",
            "ts": "1",
            "state": "pending",
        },
        {
            "msg_id": "old",
            "sender": "replied",
            "kind": "needs-user",
            "ts": "1",
            "state": "pending",
        },
        {
            "msg_id": "wrong-kind",
            "sender": "active",
            "kind": "info",
            "ts": "1",
            "state": "pending",
        },
    ]
    messages = [{"from": "main", "to": "replied", "ts": "2"}]
    result = open_decision_items(items, messages, {"ack"}, {"active", "replied"}, set())
    assert [item["msg_id"] for item in result] == ["open"]
    assert {"needs-user", "needs-decision", "merge-ready"} == OPEN_DECISION_KINDS


def test_open_decision_keeps_equal_timestamp_and_excludes_concluded() -> None:
    item = {
        "msg_id": "m",
        "sender": "a",
        "kind": "merge-ready",
        "ts": "2",
        "state": "pending",
    }
    assert open_decision_items(
        [item], [{"from": "main", "to": "a", "ts": "2"}], set(), {"a"}, set()
    ) == [item]
    assert not open_decision_items([item], [], set(), {"a"}, {"a"})


def test_open_decisions_matches_runner_cases() -> None:
    messages = [
        {
            "id": "open",
            "from": "active",
            "kind": "needs-user",
            "ts": "2026-10-20T12:00:00Z",
        },
        {
            "id": "acked",
            "from": "active",
            "kind": "needs-decision",
            "ts": "2026-10-20T12:00:00Z",
        },
        {
            "id": "concluded",
            "from": "concluded",
            "kind": "needs-user",
            "ts": "2026-10-20T12:00:00Z",
        },
        {
            "id": "resolved",
            "from": "active-open",
            "kind": "merge-ready",
            "ts": "2026-10-20T12:00:00Z",
        },
        {
            "id": "reply",
            "from": "main",
            "to": "active",
            "kind": "info",
            "ts": "2026-10-20T11:30:00Z",
        },
    ]
    items = [
        {
            "msg_id": message["id"],
            "sender": message["from"],
            "kind": message["kind"],
            "ts": message["ts"],
            "state": "dismissed" if message["id"] == "resolved" else "pending",
        }
        for message in messages
        if message["from"] != "main"
    ]
    result = open_decision_items(
        items,
        messages,
        {"acked"},
        {"active", "active-open", "concluded"},
        {"concluded"},
    )
    assert [item["msg_id"] for item in result] == ["open"]
