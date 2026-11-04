from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from varde_data.repos.addresses import AddressRepository
from varde_workflow.binding import BindingStore
from varde_workflow.inbox import append_message
from varde_workflow.relay_plan import next_due
from varde_workflow.relay_state import planning_state
from varde_workflow.relay_wait import once, wait

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
TOKEN = "token-1"  # noqa: S105 - Stable fake token used by relay wait fixtures.


def setup_working(tmp_path: Path, *, binding: bool = False) -> Path:
    working = tmp_path / "working"
    inbox = working / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    current = inbox / "addresses" / "mailman" / "current"
    current.parent.mkdir(parents=True)
    current.write_text(json.dumps({"token_id": TOKEN}))
    if binding:
        addresses = inbox / "addresses" / "worker"
        addresses.mkdir(parents=True)
        (addresses / "current").write_text(
            json.dumps({"session_key": "claude-key", "token_id": "worker-token"})
        )
        bindings = inbox / "bindings"
        bindings.mkdir()
        (bindings / "claude-key.json").write_text(
            json.dumps(
                {
                    "address": "worker",
                    "token_id": "worker-token",
                    "harness": "claude",
                    "session_id": "s",
                    "cwd": str(tmp_path),
                    "last_seen": (NOW - timedelta(minutes=10)).isoformat(),
                    "wake_context": {
                        "harness": "claude",
                        "session_id": "s",
                        "cwd": str(tmp_path),
                    },
                }
            )
        )
    return working


def due_message(working: Path, kind: str = "needs-user", *, at: datetime = NOW) -> None:
    append_message("main", "worker", kind, "please act", working=working, now=at)


def bind_worker(working: Path, at: datetime) -> None:
    store = BindingStore(working)
    marker = store.issue("worker", now=at)
    assert store.redeem(marker, "session", "claude", str(working), now=at)


def test_once_returns_immediate_due_action_and_schema(tmp_path: Path) -> None:
    working = setup_working(tmp_path, binding=True)
    due_message(working)

    result = once(working, TOKEN, NOW)

    assert result["schema"] == "varde-relay/1"
    assert result["status"] == "actions"
    assert len(result["actions"]) == 1
    assert result["actions"][0]["to"] == "worker"
    assert result["mailman"]["id"] == TOKEN


def test_once_escalates_regular_unbound_message_after_ten_minutes(
    tmp_path: Path,
) -> None:
    from varde_workflow.inbox import read_all

    working = setup_working(tmp_path)
    message = append_message(
        "sender",
        "unbound-worker",
        "info",
        "regular work",
        working=working,
        now=NOW - timedelta(minutes=11),
    )

    once(working, TOKEN, NOW)

    notices = [
        row
        for row in read_all(working)
        if row.from_ == "relay" and row.to == "main" and row.kind == "info-failure"
    ]
    assert len(notices) == 1
    assert (message.id or "") in notices[0].text


def test_wait_returns_none_only_at_timeout(tmp_path: Path) -> None:
    working = setup_working(tmp_path)
    clock = {"now": NOW, "mono": 0.0, "polls": 0}

    def poll(delay: float) -> None:
        clock["polls"] += 1
        clock["now"] += timedelta(seconds=delay)
        clock["mono"] += delay

    result = wait(
        working,
        TOKEN,
        6,
        now=lambda: clock["now"],
        monotonic=lambda: clock["mono"],
        poll=poll,
    )

    assert result["status"] == "none"
    assert result["waited_s"] == 6
    assert clock["now"] == NOW + timedelta(seconds=6)
    assert clock["polls"] == 3


def test_wait_due_is_immediate_and_only_one_waiter_leases(tmp_path: Path) -> None:
    working = setup_working(tmp_path, binding=True)
    due_message(working)

    first = wait(working, TOKEN, 60, now=lambda: NOW)
    clock = {"now": NOW, "mono": 0.0}

    def poll(delay: float) -> None:
        clock["now"] += timedelta(seconds=delay)
        clock["mono"] += delay

    second = wait(
        working,
        TOKEN,
        4,
        now=lambda: clock["now"],
        monotonic=lambda: clock["mono"],
        poll=poll,
    )

    assert len(first["actions"]) == 1
    assert second["status"] == "none"


def test_wait_detects_new_mailman_token_and_returns_superseded(tmp_path: Path) -> None:
    working = setup_working(tmp_path)
    (working / ".cache/inbox/addresses/mailman/current").write_text(
        json.dumps({"token_id": "new-token"})
    )

    result = wait(working, TOKEN, 60, now=lambda: NOW)

    assert result["status"] == "superseded"


def test_wait_without_lease_ignores_partial_trailing_line(
    tmp_path: Path,
) -> None:
    working = setup_working(tmp_path)
    clock = {"now": NOW, "mono": 0.0, "polls": 0}
    messages = working / ".cache/inbox/messages.jsonl"

    def poll(delay: float) -> None:
        clock["polls"] += 1
        if clock["polls"] == 1:
            messages.write_bytes(b'{"partial":')
            clock["now"] += timedelta(hours=2)
            clock["mono"] += delay
        else:
            clock["now"] += timedelta(seconds=delay)
            clock["mono"] += delay

    result = wait(
        working,
        TOKEN,
        1,
        now=lambda: clock["now"],
        monotonic=lambda: clock["mono"],
        poll=poll,
    )
    assert result["status"] == "none"
    state = planning_state(working)
    assert not any(event.get("event") == "slept" for event in state["events"])
    assert not state["messages"]


def test_next_due_exposes_digest_timer(tmp_path: Path) -> None:
    working = setup_working(tmp_path, binding=True)
    due_message(working, "info", at=NOW - timedelta(seconds=30))
    assert next_due(planning_state(working), NOW) == NOW + timedelta(seconds=90)


@pytest.mark.parametrize(
    ("boundary", "delay_seconds"),
    (
        ("digest", 120),
        ("grace", 120),
        ("backoff", 60),
        ("lease", 300),
        ("receipt", 600),
        ("unbound", 120),
    ),
)
def test_wait_wakes_at_each_planned_timer_boundary(
    tmp_path: Path, boundary: str, delay_seconds: int
) -> None:
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_workflow.inbox import record_relay_event

    working = setup_working(tmp_path)
    addresses = open_data(working, load_data_config()).addresses
    message_at = NOW
    if boundary == "digest":
        bind_worker(working, NOW - timedelta(minutes=10))
        message = append_message(
            "main", "worker", "info", "digest", working=working, now=NOW
        )
    elif boundary == "grace":
        bind_worker(working, NOW)
        message = append_message(
            "main", "worker", "stale", "grace", working=working, now=NOW
        )
    elif boundary == "backoff":
        message_at = NOW - timedelta(minutes=10)
        bind_worker(working, message_at)
        message = append_message(
            "main", "worker", "blocked", "retry", working=working, now=message_at
        )
        record_relay_event(working, message.id or "", "worker", "failed", now=NOW)
    elif boundary == "lease":
        message_at = NOW - timedelta(minutes=10)
        bind_worker(working, message_at)
        message = append_message(
            "main", "worker", "blocked", "lease", working=working, now=message_at
        )
        addresses.lease_actions(
            [{"to": "worker", "message_ids": [message.id or ""]}],
            "prior-token",
            NOW,
            lease_for=timedelta(seconds=delay_seconds),
        )
    elif boundary == "receipt":
        message_at = NOW - timedelta(minutes=10)
        bind_worker(working, message_at)
        message = append_message(
            "main", "worker", "blocked", "receipt", working=working, now=message_at
        )
        addresses.record_send_liveness(message.id or "", "worker", NOW)
        record_relay_event(
            working,
            message.id or "",
            "worker",
            "pushed",
            now=NOW,
            token_id=TOKEN,
            action_id="receipt-action",
            harness="claude",
        )
    else:
        message = append_message(
            "main", "worker", "blocked", "unbound", working=working, now=NOW
        )
        assert boundary == "unbound"
    assert message.id

    clock = {"now": NOW, "mono": 0.0, "delays": []}

    def poll(delay: float) -> None:
        clock["delays"].append(delay)
        clock["now"] += timedelta(seconds=delay)
        clock["mono"] += delay

    result = wait(
        working,
        TOKEN,
        delay_seconds + 2,
        now=lambda: clock["now"],
        monotonic=lambda: clock["mono"],
        poll=poll,
    )

    elapsed = sum(clock["delays"])
    assert delay_seconds <= elapsed <= delay_seconds + 2
    assert clock["now"] == NOW + timedelta(seconds=elapsed)
    if boundary == "unbound":
        from varde_workflow.relay_state import load

        assert result["status"] == "none"
        assert any(
            event.get("event") == "escalated" and event.get("source_id") == message.id
            for event in load(working)["events"]
        )
    else:
        assert result["actions"][0]["message_ids"] == [message.id]


def test_partial_jsonl_line_completed_in_second_write_wakes_once(
    tmp_path: Path,
) -> None:
    working = setup_working(tmp_path, binding=True)
    clock = {"now": NOW, "mono": 0.0, "polls": 0}
    path = working / ".cache/inbox/messages.jsonl"
    row = (
        json.dumps(
            {
                "ts": NOW.isoformat(),
                "from": "main",
                "to": "worker",
                "kind": "needs-user",
                "text": "please act",
                "id": "m-12345678",
            }
        ).encode()
        + b"\n"
    )

    def poll(_delay: float) -> None:
        clock["polls"] += 1
        if clock["polls"] == 1:
            path.write_bytes(row[: len(row) // 2])
        elif clock["polls"] == 2:
            with path.open("ab") as stream:
                stream.write(row[len(row) // 2 :])
        clock["now"] += timedelta(milliseconds=50)
        clock["mono"] += 0.05

    result = wait(
        working,
        TOKEN,
        10,
        now=lambda: clock["now"],
        monotonic=lambda: clock["mono"],
        poll=poll,
    )

    assert result["status"] == "actions"
    assert len(result["actions"]) == 1
    assert clock["polls"] == 2


def test_concurrent_wait_loser_reenters_after_lease(
    tmp_path: Path, monkeypatch
) -> None:
    from varde_workflow import relay_wait

    working = setup_working(tmp_path, binding=True)
    due_message(working)
    barrier = threading.Barrier(2)
    service_factory = relay_wait._service

    class LeaseBarrierRepository:
        def __init__(self, repository):
            self.repository = repository

        def __getattr__(self, name):
            return getattr(self.repository, name)

        def lease_actions(self, *args, **kwargs):
            barrier.wait(timeout=2)
            return self.repository.lease_actions(*args, **kwargs)

    def synchronized_service(*args, **kwargs):
        service = service_factory(*args, **kwargs)
        service.addresses = cast(
            "AddressRepository", LeaseBarrierRepository(service.addresses)
        )
        return service

    monkeypatch.setattr(relay_wait, "_service", synchronized_service)

    def run_wait() -> dict:
        clock = {"now": NOW, "mono": 0.0}

        def poll(delay: float) -> None:
            clock["now"] += timedelta(seconds=delay)
            clock["mono"] += delay

        return wait(
            working,
            TOKEN,
            4,
            now=lambda: clock["now"],
            monotonic=lambda: clock["mono"],
            poll=poll,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: run_wait(), range(2)))

    assert sum(len(result.get("actions", [])) for result in results) == 1
    assert sum(result["status"] == "none" for result in results) == 1


def test_sleep_gap_does_not_expire_an_action_lease(tmp_path: Path) -> None:
    working = setup_working(tmp_path, binding=True)
    due_message(working)
    first = once(working, TOKEN, NOW)
    assert len(first["actions"]) == 1
    clock = {"now": NOW, "mono": 0.0, "polls": 0}

    def poll(delay: float) -> None:
        clock["polls"] += 1
        if clock["polls"] == 1:
            clock["now"] += timedelta(hours=2)
            clock["mono"] += 4 * 60 * 60
        else:
            clock["now"] += timedelta(seconds=max(delay, 1))
            clock["mono"] += max(delay, 1)

    result = wait(
        working,
        TOKEN,
        4 * 60 * 60,
        now=lambda: clock["now"],
        monotonic=lambda: clock["mono"],
        poll=poll,
    )

    assert result["status"] == "none"
    assert not result.get("actions")
    assert clock["polls"] >= 2


def test_response_exposes_the_real_retry_attempt(tmp_path: Path) -> None:
    from varde_workflow.relay_state import confirm

    working = setup_working(tmp_path, binding=True)
    due_message(working)
    first = once(working, TOKEN, NOW)
    action = first["actions"][0]
    confirm(working, action["action_id"], "failed", NOW)

    retry = once(working, TOKEN, NOW + timedelta(minutes=2))

    assert retry["actions"][0]["attempt"] == 2


def test_pulse_mailman_uses_legacy_state_current_when_pointer_is_absent(
    tmp_path: Path,
) -> None:
    from varde_workflow.pulse_mail import mailman_status

    state_path = tmp_path / ".cache" / "inbox" / "relay" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "current_mailman": "legacy-token",
                "events": [
                    {
                        "event": "waiting",
                        "token_id": "legacy-token",
                        "at": NOW.isoformat(),
                    }
                ],
            }
        )
    )

    assert mailman_status(tmp_path, NOW) == "alive"


def test_msg_status_ignores_legacy_state_current_when_pointer_is_absent(
    tmp_path: Path,
) -> None:
    from varde_workflow.msg_status import load_report

    state_path = tmp_path / ".cache" / "inbox" / "relay" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"current_mailman": "legacy-token"}))

    assert load_report(str(tmp_path), NOW)["runner_relay"] == "down"
