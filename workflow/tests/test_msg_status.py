from __future__ import annotations

import json
import time
from argparse import Namespace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from varde_workflow.binding import BindingStore
from varde_workflow.commands.msg_status import run
from varde_workflow.msg_status import (
    banner,
    build_report,
    filter_retired,
    find_stray_stores,
    load_report,
)

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def test_find_stray_stores_excludes_configured_store_and_generated_dirs(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    expected = repo / "memory-bank" / "working"
    configured_inbox = expected / ".cache" / "inbox"
    stray = repo / "runner" / ".cache" / "inbox"
    non_store = repo / "runner" / "module" / ".cache" / "inbox"
    ignored = repo / ".venv" / ".cache" / "inbox"
    for inbox in (configured_inbox, stray, non_store, ignored):
        inbox.mkdir(parents=True)

    memory_bank_stray = repo / "runner" / "memory-bank" / "working" / ".cache" / "inbox"
    memory_bank_stray.mkdir(parents=True)
    assert find_stray_stores(repo, expected) == [memory_bank_stray]
    assert find_stray_stores(None, expected) == []


def test_report_computes_pending_latency_and_cli_main_reads() -> None:
    messages = [
        {
            "id": "m1",
            "to": "worker",
            "kind": "needs-user",
            "ts": "2026-10-17T11:40:00Z",
        },
        {"id": "m2", "to": "worker", "kind": "info", "ts": "2026-10-17T11:45:00Z"},
    ]
    deliveries = [
        {
            "message_id": "m1",
            "reader": "worker",
            "event": "delivered",
            "via": "hook",
            "at": "2026-10-17T11:41:00Z",
        },
        {
            "message_id": "m1",
            "reader": "worker",
            "event": "acked",
            "via": "cli",
            "at": "2026-10-17T11:42:00Z",
        },
        {
            "message_id": "m2",
            "reader": "worker",
            "event": "acked",
            "via": "cli",
            "at": "2026-10-17T11:52:00Z",
        },
        {
            "message_id": "m2",
            "reader": "main",
            "event": "delivered",
            "via": "cli",
            "at": "2026-10-17T11:50:00Z",
        },
        {
            "message_id": "m2",
            "reader": "main",
            "event": "acked",
            "via": "cli",
            "at": "2026-10-17T11:51:00Z",
        },
    ]
    report = build_report(messages, deliveries, [], [], NOW)
    worker = next(item for item in report["addresses"] if item["address"] == "worker")
    assert worker["total"] == 2
    assert worker["unread"] == 1
    assert worker["oldest_unread_age_seconds"] == 900
    assert worker["oldest_undelivered_age_seconds"] is None
    assert report["send_to_delivered_seconds"]["p50"] == 60
    assert report["send_to_ack_seconds"]["p90"] == 420
    assert report["cli_main_reads"] == {"count": 1, "last_at": "2026-10-17T11:51:00Z"}


def test_thresholds_and_unbound_pending_drive_banner() -> None:
    messages = [
        {
            "id": "urgent",
            "to": "worker",
            "kind": "blocked",
            "ts": "2026-10-17T11:49:59Z",
        },
        {"id": "regular", "to": "guest", "kind": "info", "ts": "2026-10-17T11:29:59Z"},
    ]
    report = build_report(messages, [], [], [], NOW)
    assert report["exit_code"] == 1
    assert report["unbound_pending"] == ["guest", "worker"]
    assert banner(report)


def test_healthy_report_has_no_banner() -> None:
    now = NOW
    messages = [{"id": "fresh", "to": "main", "kind": "info", "ts": now.isoformat()}]
    report = build_report(messages, [], [], [{"address": "main"}], now)
    assert report["exit_code"] == 0
    assert banner(report) is None


def test_event_alert_window_uses_injected_clock() -> None:
    recent = {"event": "supersede", "at": (NOW - timedelta(hours=23)).isoformat()}
    stale = {"event": "token-reuse", "at": (NOW - timedelta(hours=25)).isoformat()}
    report = build_report([], [], [recent, stale], [], NOW)
    assert report["events"] == [recent]
    assert report["exit_code"] == 1


def test_corrupt_log_skips_bad_lines_and_returns_healthy_status(tmp_path: Path) -> None:
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "events.jsonl").write_text("{bad\n{}\n")
    assert run(Namespace(now=None, json=True), tmp_path) == 0


def test_delivery_annotations_use_first_delivery_and_disposition_is_not_unread() -> (
    None
):
    messages = [
        {"id": "sent", "to": "main", "kind": "info", "ts": "2026-10-17T11:00:00Z"},
        {"id": "discarded", "to": "main", "kind": "info", "ts": "2026-10-17T11:00:00Z"},
    ]
    deliveries = [
        {
            "message_id": "sent",
            "reader": "main",
            "event": "delivered",
            "via": "hook",
            "at": "2026-10-17T11:01:00Z",
        },
        {
            "message_id": "sent",
            "reader": "main",
            "event": "delivered",
            "via": "cli",
            "at": "2026-10-17T11:10:00Z",
        },
        {
            "message_id": "discarded",
            "reader": "main",
            "event": "dropped",
            "via": "cli",
            "at": "2026-10-17T11:02:00Z",
        },
    ]
    report = build_report(messages, deliveries, [], [{"address": "main"}], NOW)
    main = report["addresses"][0]
    assert main["unread"] == 0
    assert main["delivered_not_acked"] == 1
    assert report["send_to_delivered_seconds"]["p50"] == 60


def test_urgent_mail_without_mailman_is_bad_after_three_minutes() -> None:
    sent_at = "2026-10-17T11:51:00Z"
    report = build_report(
        [{"id": "fresh-urgent", "to": "main", "kind": "blocked", "ts": sent_at}],
        [],
        [],
        [{"address": "main"}],
        NOW,
    )
    assert report["exit_code"] == 1
    assert "runner relay: down" in (banner(report) or "")


def test_delivered_or_below_watermark_urgent_mail_is_not_pending() -> None:
    old = (NOW - timedelta(minutes=20)).isoformat()
    delivered = {"id": "delivered", "to": "main", "kind": "blocked", "ts": old}
    below = {
        "id": "below",
        "to": "main",
        "kind": "blocked",
        "ts": old,
        "_below_watermark": True,
    }
    delivery = {
        "message_id": "delivered",
        "reader": "main",
        "event": "delivered",
        "at": NOW.isoformat(),
    }
    for message, records in ((delivered, [delivery]), (below, [])):
        report = build_report([message], records, [], [{"address": "main"}], NOW)
        assert report["runner_relay_down_with_urgent_mail"] is False
        assert report["exit_code"] == 0


def bind(working: Path, address: str, session: str, at: datetime) -> None:
    store = BindingStore(working)
    marker = store.issue(address, now=at)
    assert store.redeem(marker, session, "claude", str(working), now=at)


def test_exit_rules_include_regular_urgent_due_and_unreviewed_events(
    tmp_path: Path,
) -> None:
    bind(tmp_path, "urgent", "u", NOW)
    urgent = {
        "id": "u1",
        "to": "urgent",
        "kind": "blocked",
        "ts": (NOW - timedelta(minutes=3)).isoformat(),
    }
    report = build_report([urgent], [], [], BindingStore(tmp_path).list_bindings(), NOW)
    assert report["exit_code"] == 1
    regular = {
        "id": "r1",
        "to": "x",
        "kind": "info",
        "ts": (NOW - timedelta(minutes=29)).isoformat(),
    }
    assert build_report([regular], [], [], [], NOW)["exit_code"] == 1
    assert (
        build_report([regular], [], [], [], NOW, {"runner_relay": "up"})["exit_code"]
        == 1
    )
    stale_regular = regular | {"ts": (NOW - timedelta(minutes=31)).isoformat()}
    assert (
        build_report([stale_regular], [], [], [], NOW, {"runner_relay": "up"})[
            "exit_code"
        ]
        == 1
    )
    stale_urgent = urgent | {"ts": (NOW - timedelta(minutes=11)).isoformat()}
    assert (
        build_report([stale_urgent], [], [], [], NOW, {"runner_relay": "up"})[
            "exit_code"
        ]
        == 1
    )
    for event in ("suspect", "misdelivered", "token-reuse", "supersede"):
        recent = {"event": event, "at": (NOW - timedelta(hours=23)).isoformat()}
        assert build_report([], [], [recent], [], NOW)["exit_code"] == 1


def test_suspect_delivery_record_alerts_through_load_report(tmp_path: Path) -> None:
    from varde_workflow.commands.msg import append_message
    from varde_workflow.inbox import record_relay_event

    bind(tmp_path, "worker", "worker-session", NOW)
    message = append_message(
        "sender", "worker", "blocked", "needs review", working=tmp_path, now=NOW
    )
    record_relay_event(tmp_path, message.id or "", "worker", "suspect", now=NOW)

    report = load_report(str(tmp_path), NOW)

    assert report["exit_code"] == 1
    assert report["messages"][0]["suspect"] == 1
    assert report["events"][0]["event"] == "suspect"


def test_mailman_states_and_stopped_reading(tmp_path: Path) -> None:
    bind(tmp_path, "worker", "w", NOW - timedelta(hours=1))
    store = BindingStore(tmp_path)
    binding = store.list_bindings()[0]
    report = build_report(
        [
            {
                "id": "old",
                "to": "worker",
                "kind": "info",
                "ts": (NOW - timedelta(minutes=11)).isoformat(),
            }
        ],
        [],
        [],
        [binding],
        NOW,
    )
    assert report["stopped_reading"] == [{"address": "worker", "newer_binding": None}]
    idle = {**binding, "last_seen": (NOW - timedelta(minutes=31)).isoformat()}
    pushed = [
        {
            "event": "pushed",
            "reader": "worker",
            "message_id": "old",
            "at": (NOW - timedelta(minutes=5)).isoformat(),
        }
    ]
    assert (
        build_report(
            [
                {
                    "id": "old",
                    "to": "worker",
                    "kind": "info",
                    "ts": (NOW - timedelta(minutes=11)).isoformat(),
                }
            ],
            pushed,
            [],
            [idle],
            NOW,
        )["stopped_reading"]
        == []
    )
    expired_lease = {
        "address": "worker",
        "created_at": (NOW - timedelta(minutes=20)).isoformat(),
        "expires_at": (NOW - timedelta(minutes=15)).isoformat(),
    }
    assert (
        build_report(
            [
                {
                    "id": "old",
                    "to": "worker",
                    "kind": "info",
                    "ts": (NOW - timedelta(minutes=11)).isoformat(),
                }
            ],
            [],
            [],
            [idle],
            NOW,
            {"runner_relay": "down", "leases": [expired_lease]},
        )["stopped_reading"]
        == []
    )
    assert load_report(str(tmp_path), NOW)["runner_relay"] == "down"

    newer_store = BindingStore(tmp_path / "newer")
    old_marker = newer_store.issue("worker", now=NOW - timedelta(hours=1))
    assert newer_store.redeem(
        old_marker, "old-session", "claude", str(tmp_path), now=NOW - timedelta(hours=1)
    )
    new_marker = newer_store.issue(
        "worker", supersede=True, now=NOW - timedelta(minutes=5)
    )
    assert newer_store.redeem(
        new_marker,
        "new-session",
        "claude",
        str(tmp_path),
        now=NOW - timedelta(minutes=5),
    )
    old_binding = next(
        item
        for item in (tmp_path / "newer/.cache/inbox/bindings").glob("*.json")
        if json.loads(item.read_text()).get("session_id") == "old-session"
    )
    old_record = json.loads(old_binding.read_text())
    newer_record = next(item for item in newer_store.list_bindings())
    stopped = build_report(
        [
            {
                "id": "old",
                "to": "worker",
                "kind": "info",
                "ts": (NOW - timedelta(minutes=11)).isoformat(),
            }
        ],
        [],
        [],
        [old_record, newer_record],
        NOW,
    )
    assert stopped["stopped_reading"] == [
        {"address": "worker", "newer_binding": "new-session"}
    ]


def test_mailman_alive_and_dead_states(tmp_path: Path) -> None:
    from varde_workflow.relay_state import heartbeat

    bind(tmp_path, "mailman", "runner-test", NOW)
    token = BindingStore(tmp_path).repo.current_token("mailman")
    heartbeat(tmp_path, token, "waiting", NOW)
    report = load_report(str(tmp_path), NOW)
    assert report["runner_relay"] == "up"
    assert "mailmen" not in report
    heartbeat(tmp_path, token, "ended", NOW + timedelta(seconds=1))
    assert (
        load_report(str(tmp_path), NOW + timedelta(seconds=1))["runner_relay"] == "down"
    )


def test_runner_relay_status_uses_fresh_waiting_identity_fixture(
    tmp_path: Path,
) -> None:
    token_id = "290060fa56caff09"  # noqa: S105 - Live relay identity fixture.
    state = {
        "current_mailman": token_id,
        "mailman_started": {token_id: "2026-10-24T11:51:52.721912Z"},
        "mailman_instances": {token_id: "process:0"},
        "events": [
            {
                "event": "waiting",
                "token_id": token_id,
                "at": "2026-10-24T11:51:52.721912Z",
                "expect_return_by": "2026-10-24T11:52:52.721912Z",
            }
        ],
    }
    relay_dir = tmp_path / ".cache" / "inbox" / "relay"
    relay_dir.mkdir(parents=True)
    (relay_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    report = load_report(str(tmp_path), datetime(2026, 10, 24, 11, 52, 52, tzinfo=UTC))

    assert report["runner_relay"] == "up"


def test_runner_relay_status_rejects_stale_waiting_identity_fixture(
    tmp_path: Path,
) -> None:
    token_id = "290060fa56caff09"  # noqa: S105 - Live relay identity fixture.
    state = {
        "current_mailman": token_id,
        "events": [
            {
                "event": "waiting",
                "token_id": token_id,
                "at": "2026-10-24T11:51:52.721912Z",
                "expect_return_by": "2026-10-24T11:52:52.721912Z",
            }
        ],
    }
    relay_dir = tmp_path / ".cache" / "inbox" / "relay"
    relay_dir.mkdir(parents=True)
    (relay_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    report = load_report(str(tmp_path), datetime(2026, 10, 24, 11, 54, 0, tzinfo=UTC))

    assert report["runner_relay"] == "down"


def test_runner_relay_state_and_status_text_age(tmp_path: Path) -> None:
    from varde_workflow.commands.msg_status import _text

    bind(tmp_path, "worker", "worker-session", NOW)
    bind(tmp_path, "mailman", "runner-test", NOW)
    from varde_workflow.relay_state import heartbeat

    heartbeat(
        tmp_path,
        BindingStore(tmp_path).repo.current_token("mailman"),
        "waiting",
        NOW,
    )
    report = build_report(
        [
            {
                "id": "old",
                "to": "worker",
                "kind": "info",
                "ts": (NOW - timedelta(minutes=5)).isoformat(),
            }
        ],
        [],
        [],
        [],
        NOW,
    )
    worker = next(row for row in report["addresses"] if row["address"] == "worker")
    assert "300s oldest undelivered" in _text({**report, "runner_relay": "up"})
    assert worker["oldest_undelivered_age_seconds"] == 300


def test_load_report_10k_lines_stays_within_hook_budget(tmp_path: Path) -> None:
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    messages = [
        {
            "id": f"m-{index}",
            "ts": NOW.isoformat(),
            "from": "sender",
            "to": "worker",
            "kind": "info",
            "text": "message",
        }
        for index in range(10_000)
    ]
    deliveries = [
        {
            "message_id": f"m-{index}",
            "reader": "worker",
            "event": "pushed",
            "at": NOW.isoformat(),
        }
        for index in range(10_000)
    ]
    (inbox / "messages.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in messages)
    )
    (inbox / "deliveries.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in deliveries)
    )

    started = time.perf_counter()
    report = load_report(str(tmp_path), NOW)
    elapsed = time.perf_counter() - started

    assert len(report["messages"]) == 10_000
    assert elapsed < 5


def test_done_is_urgent_only_on_a_plan_owner_route() -> None:
    bindings = [
        {"address": "owner", "last_seen": (NOW - timedelta(hours=1)).isoformat()},
        {"address": "worker", "last_seen": (NOW - timedelta(hours=1)).isoformat()},
    ]
    base = {
        "id": "m-1",
        "to": "owner",
        "kind": "done",
        "ts": (NOW - timedelta(minutes=4)).isoformat(),
    }
    other_sender = build_report([{**base, "from": "worker"}], [], [], bindings, NOW)
    plan_sender = build_report([{**base, "from": "plan-id"}], [], [], bindings, NOW)

    assert other_sender["runner_relay_down_with_urgent_mail"] is False
    assert plan_sender["runner_relay_down_with_urgent_mail"] is True


def _retired_mailman_state(working: Path) -> None:
    from varde_workflow.retired import retire

    inbox = working / ".cache" / "inbox"
    relay = inbox / "relay"
    relay.mkdir(parents=True)
    (relay / "state.json").write_text(
        json.dumps(
            {
                "mailman_started": {
                    "old-token": NOW.isoformat(),
                    "new-token": NOW.isoformat(),
                }
            }
        )
    )
    current = inbox / "addresses" / "mailman" / "current"
    current.parent.mkdir(parents=True)
    current.write_text(json.dumps({"token_id": "new-token"}))
    retire(working, {"retired-address"}, {"old-token"}, NOW)


def test_status_skips_retired_address_and_noncurrent_mailman(tmp_path, capsys) -> None:
    _retired_mailman_state(tmp_path)
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    message = {
        "id": "old-message",
        "ts": NOW.isoformat(),
        "from": "main",
        "to": "retired-address",
        "kind": "info",
        "text": "already read",
    }
    log = inbox / "messages.jsonl"
    log.write_text(json.dumps(message) + "\n")
    index = inbox / "index" / "retired-address.json"
    index.parent.mkdir()
    index.write_text(json.dumps({"watermark": log.stat().st_size}))

    assert run(Namespace(now=NOW.isoformat(), json=True), tmp_path) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["addresses"] == []
    assert "mailmen" not in report
    assert report["runner_relay"] == "down"


def test_retired_address_reappears_with_new_pending_mail(tmp_path, capsys) -> None:
    _retired_mailman_state(tmp_path)
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    first = {
        "id": "before-prune",
        "ts": NOW.isoformat(),
        "from": "main",
        "to": "retired-address",
        "kind": "info",
        "text": "old",
    }
    second = {
        **first,
        "id": "after-prune",
        "ts": (NOW + timedelta(seconds=1)).isoformat(),
        "text": "new",
    }
    old_line = json.dumps(first) + "\n"
    log = inbox / "messages.jsonl"
    log.write_text(old_line + json.dumps(second) + "\n")
    index = inbox / "index" / "retired-address.json"
    index.parent.mkdir()
    index.write_text(json.dumps({"watermark": len(old_line.encode())}))

    run(Namespace(now=NOW.isoformat(), json=True), tmp_path)

    report = json.loads(capsys.readouterr().out)
    address = next(
        row for row in report["addresses"] if row["address"] == "retired-address"
    )
    assert address["unread"] == 1


def test_filter_retired_recomputes_bad_and_exit_code() -> None:
    report = build_report(
        [],
        [],
        [
            {
                "event": "supersede",
                "address": "retired-address",
                "at": (NOW - timedelta(hours=1)).isoformat(),
            }
        ],
        [],
        NOW,
    )
    assert report["bad"] is True

    filtered = filter_retired(report, {"retired-address": NOW.isoformat()})

    assert filtered["addresses"] == []
    assert filtered["events"] == []
    assert filtered["bad"] is False
    assert filtered["exit_code"] == 0


def test_filter_retired_hides_old_unread_keeps_new_and_recomputes_overdue() -> None:
    old = {
        "id": "old",
        "to": "old-address",
        "kind": "info",
        "ts": (NOW - timedelta(hours=2)).isoformat(),
    }
    new = {
        "id": "new",
        "to": "new-address",
        "kind": "info",
        "ts": (NOW - timedelta(minutes=5)).isoformat(),
    }
    report = build_report([old, new], [], [], [], NOW)

    filtered = filter_retired(
        report,
        {
            "old-address": (NOW - timedelta(hours=1)).isoformat(),
            "new-address": (NOW - timedelta(minutes=10)).isoformat(),
        },
    )

    assert [row["address"] for row in filtered["addresses"]] == ["new-address"]
    assert filtered["unbound_pending"] == ["new-address"]
    assert filtered["overdue"] is False
    assert filtered["bad"] is True


def test_retired_address_stays_hidden_from_all_status_lists() -> None:
    old = {
        "id": "old",
        "to": "retired-address",
        "kind": "info",
        "ts": (NOW - timedelta(hours=2)).isoformat(),
    }
    report = build_report([old], [], [], [], NOW)
    report["stopped_reading"] = [{"address": "retired-address"}]
    filtered = filter_retired(report, {"retired-address": NOW.isoformat()})

    assert filtered["addresses"] == []
    assert filtered["unbound_pending"] == []
    assert filtered["stopped_reading"] == []
    assert filtered["overdue"] is False
    assert filtered["bad"] is False


def test_retired_urgent_mail_does_not_keep_no_mailman_bad() -> None:
    urgent = {
        "id": "urgent",
        "to": "retired-address",
        "kind": "blocked",
        "ts": (NOW - timedelta(minutes=5)).isoformat(),
    }
    report = build_report([urgent], [], [], [], NOW)
    assert report["runner_relay_down_with_urgent_mail"] is True

    filtered = filter_retired(report, {"retired-address": NOW.isoformat()})

    assert filtered["runner_relay_down_with_urgent_mail"] is False
    assert filtered["bad"] is False


def test_recent_alert_ignores_dead_supersede_but_keeps_live_and_legacy() -> None:
    from varde_workflow.msg_status import _recent_alerts

    events = [
        {"event": "supersede", "prior_live": False, "at": NOW.isoformat()},
        {"event": "supersede", "prior_live": True, "at": NOW.isoformat()},
        {"event": "supersede", "at": NOW.isoformat()},
    ]

    assert _recent_alerts(events, NOW) == events[1:]


def test_filter_retired_does_not_expose_legacy_mailman_generations() -> None:
    report = build_report(
        [],
        [],
        [],
        [],
        NOW,
        {"runner_relay": "down"},
    )

    filtered = filter_retired(report, {"mailman:retired": NOW.isoformat()})

    assert "mailmen" not in filtered
