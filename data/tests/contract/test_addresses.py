from __future__ import annotations

import hashlib
import multiprocessing
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from addresses_backends import BackendRegistration, backend_registry
from varde_data.errors import Locked
from varde_data.locking import file_lock
from varde_data.records.addresses import ConfirmStatus, ReaderContext
from varde_data.repos.addresses import AddressRepository

NOW = datetime(2026, 1, 1, tzinfo=UTC)
CTX = ReaderContext(cwd="/work")


@pytest.fixture(params=tuple(backend_registry()), ids=tuple(backend_registry()))
def address_backend(request: pytest.FixtureRequest) -> BackendRegistration:
    return backend_registry()[request.param]


@pytest.fixture
def working(tmp_path: Path) -> Path:
    return tmp_path / "working"


@pytest.fixture
def addresses(address_backend: BackendRegistration, working: Path) -> AddressRepository:
    return address_backend.factory(working)


@pytest.fixture
def require_relay_storage(
    request: pytest.FixtureRequest, address_backend: BackendRegistration
) -> None:
    relay_cases = {
        "test_lease_busy_confirming_prompt_rewrite_and_shrink",
        "test_confirm_unknown_result_resume_and_attempt_dedupe",
        "test_renew_event_trimming_sleep_and_send_liveness_cap",
        "test_liveness_return_cycles_and_sleep_adjusted_age",
        "test_heartbeat_if_waiting_requires_current_waiting_token",
        "test_retire_reservations_wakes_and_version_changes",
        "test_pure_reads_do_not_advance_version",
        "test_every_repository_write_advances_version",
        "test_event_log_is_append_only_and_read_capability",
    }
    if (
        request.node.originalname in relay_cases
        and not address_backend.capabilities.relay_storage
    ):
        pytest.skip("backend does not yet implement relay storage")


def _reason(event: object) -> object:
    return event.details["reason"]  # type: ignore[attr-defined]


def test_issue_does_not_publish_current_and_outstanding_token_still_redeems(
    addresses: AddressRepository,
) -> None:
    first = addresses.issue("worker", now=NOW)
    assert addresses.current_token("worker") is None
    assert addresses.current_binding("worker") is None
    assert addresses.address_names() == {"worker"}
    second = addresses.issue("worker", now=NOW + timedelta(seconds=1))
    assert addresses.redeem(first, "s", "h", CTX, now=NOW)
    assert addresses.current_token("worker") is not None
    assert addresses.current_binding("worker").token_id != ""  # type: ignore[union-attr]
    assert addresses.address_names() == {"worker"}
    assert addresses.marker_error(second, NOW) == "marker superseded by a newer marker"
    assert addresses.address_names() == {"worker"}
    assert addresses.token_issue_times() == {
        "worker": (NOW, NOW + timedelta(seconds=1))
    }


def test_prune_read_methods_cover_empty_multiple_addresses_and_mailman(
    addresses: AddressRepository,
) -> None:
    assert addresses.address_names() == frozenset()
    assert addresses.token_issue_times() == {}

    addresses.issue("zeta", now=NOW + timedelta(seconds=2))
    addresses.issue("alpha", now=NOW)
    addresses.issue("zeta", now=NOW + timedelta(seconds=1))
    addresses.issue("mailman", now=NOW)

    assert addresses.address_names() == {"alpha", "zeta"}
    assert addresses.token_issue_times() == {
        "alpha": (NOW,),
        "mailman": (NOW,),
        "zeta": (NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)),
    }


def test_retired_records_overwrite_stamps_and_match_retired_sets(
    addresses: AddressRepository,
) -> None:
    later = NOW + timedelta(seconds=5)
    addresses.retire(("old", "shared"), ("token-old", "token-shared"), NOW)
    addresses.retire(("new", "shared"), ("token-new", "token-shared"), later)

    expected = {
        "old": "2026-01-01T00:00:00Z",
        "shared": "2026-01-01T00:00:05Z",
        "new": "2026-01-01T00:00:05Z",
        "mailman:token-old": "2026-01-01T00:00:00Z",
        "mailman:token-shared": "2026-01-01T00:00:05Z",
        "mailman:token-new": "2026-01-01T00:00:05Z",
    }
    assert addresses.retired_records() == expected
    assert addresses.retired().addresses == {"old", "shared", "new"}
    assert addresses.retired().tokens == {"token-old", "token-shared", "token-new"}


def test_live_refusal_supersede_and_stale_binding(addresses: AddressRepository) -> None:
    first = addresses.issue("worker", uses=2, now=NOW)
    assert addresses.redeem(first, "s1", "h", CTX, now=NOW)
    with pytest.raises(ValueError, match="supersede"):
        addresses.issue("worker", now=NOW + timedelta(seconds=1))
    assert _reason(addresses.last_refusal("worker")) == "supersede-required"
    old = addresses.issue(
        "worker", uses=2, supersede=True, now=NOW + timedelta(seconds=2)
    )
    assert addresses.redeem(old, "s2", "h", CTX, now=NOW + timedelta(seconds=2))
    assert not addresses.redeem(first, "s3", "h", CTX, now=NOW + timedelta(seconds=3))
    assert _reason(addresses.last_refusal("worker")) == "live-binding"
    assert addresses.issue("worker", now=NOW + timedelta(hours=1))


def test_runner_binding_identity_survives_different_refresh(
    addresses: AddressRepository,
) -> None:
    marker = addresses.issue("worker", now=NOW)
    runner = ReaderContext(
        cwd="/runner/workspace",
        agent_id="runner-agent",
        runner_harness="claude-cli",
        runner_endpoint="http://runner",
        runner_binding=True,
    )
    assert addresses.redeem(marker, "session", "claude", runner, now=NOW)

    assert addresses.refresh_current(
        "claude",
        "session",
        ReaderContext(
            cwd="/runner/workspace",
            agent_id="/runner/workspace",
            runner_harness="claude-cli",
            runner_endpoint="http://other-runner",
            runner_binding=True,
        ),
        NOW + timedelta(seconds=1),
    )
    binding = addresses.current_binding("worker")
    assert binding is not None
    wake = binding.extra["wake_context"]
    assert isinstance(wake, Mapping)
    assert wake["agent_id"] == "runner-agent"
    assert wake["harness"] == "claude-cli"
    assert wake["runner_endpoint"] == "http://runner"

    same_runner_refresh = ReaderContext(
        cwd="/runner/workspace",
        agent_id="runner-agent",
        runner_harness="claude-cli",
        runner_endpoint="http://runner",
    )
    assert addresses.refresh_current(
        "claude",
        "session",
        same_runner_refresh,
        NOW + timedelta(seconds=2),
    )
    binding = addresses.current_binding("worker")
    assert binding is not None
    wake = binding.extra["wake_context"]
    assert isinstance(wake, Mapping)
    assert wake["agent_id"] == "runner-agent"


def test_marker_errors_and_token_purge(addresses: AddressRepository) -> None:
    assert addresses.marker_error("malformed", NOW) == "unknown marker"
    expired = addresses.issue("expired", ttl=timedelta(seconds=1), now=NOW)
    assert (
        addresses.marker_error(expired, NOW + timedelta(seconds=1)) == "marker expired"
    )
    assert not addresses.redeem(expired, "s", "h", CTX, now=NOW + timedelta(seconds=1))
    assert _reason(addresses.last_refusal("expired")) == "expired-token"
    addresses.issue("expired", now=NOW + timedelta(seconds=2))
    assert (
        addresses.marker_error(expired, NOW + timedelta(seconds=2)) == "unknown marker"
    )


def test_idempotent_redeem_and_single_use_race(addresses: AddressRepository) -> None:
    marker = addresses.issue("worker", uses=1, now=NOW)
    assert addresses.redeem(marker, "s", "h", CTX, now=NOW)
    assert addresses.redeem(marker, "s", "h", CTX, now=NOW + timedelta(seconds=1))
    bind = next(event for event in addresses.events() if event.event == "bind")
    assert bind.at == NOW
    assert bind.address == "worker"
    assert bind.session_key == "h-" + hashlib.sha256(b"s").hexdigest()
    assert not addresses.redeem(marker, "other", "h", CTX, now=NOW)
    assert addresses.events()[-1].event == "token-reuse"


def test_fresh_token_has_one_winner_under_contention(
    addresses: AddressRepository,
) -> None:
    marker = addresses.issue("racer", uses=1, supersede=True, now=NOW)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(
            pool.map(
                lambda i: addresses.redeem(marker, f"racer-{i}", "h", CTX, now=NOW),
                range(8),
            )
        )
    assert sum(results) == 1
    assert sum(event.event == "bind" for event in addresses.events()) == 1


def test_spent_and_expired_token_reports_reuse_not_expiry(
    addresses: AddressRepository,
) -> None:
    marker = addresses.issue("worker", ttl=timedelta(seconds=10), now=NOW)
    assert addresses.redeem(marker, "s", "h", CTX, now=NOW)
    assert not addresses.redeem(marker, "t", "h", CTX, now=NOW + timedelta(seconds=20))
    assert addresses.events()[-1].event == "token-reuse"


def test_rebind_clears_gone_wake(addresses: AddressRepository) -> None:
    first = addresses.issue("worker", now=NOW)
    assert addresses.redeem(first, "s1", "h", CTX, now=NOW)
    addresses.mark_wake_gone("worker", NOW)
    second = addresses.issue("worker", supersede=True, now=NOW + timedelta(seconds=1))
    assert addresses.redeem(second, "s2", "h", CTX, now=NOW + timedelta(seconds=1))
    binding = addresses.current_binding("worker")
    assert binding is not None
    assert "wake" not in binding.extra


def test_reader_context_resolution_refresh_and_self_bind(
    addresses: AddressRepository,
) -> None:
    marker = addresses.issue("worker", now=NOW)
    assert addresses.resolve_reader("h", "s", marker, CTX, NOW) == "worker"
    assert (
        addresses.resolve_reader(
            "h", "s", None, ReaderContext(cwd="/changed"), NOW + timedelta(seconds=30)
        )
        == "worker"
    )
    binding = addresses.current_binding("worker")
    assert binding is not None
    assert binding.extra["cwd"] == "/work"
    context = ReaderContext(
        cwd="/changed",
        paseo_id="p",
        agent_id="a",
        runner_harness="codex",
        runner_endpoint="endpoint",
        extra={"future_field": {"preserve": True}},
    )
    assert (
        addresses.resolve_reader("h", "s", None, context, NOW + timedelta(seconds=61))
        == "worker"
    )
    binding = addresses.current_binding("worker")
    assert binding is not None
    wake = binding.extra["wake_context"]
    assert isinstance(wake, Mapping)
    assert wake["harness"] == "codex"
    assert wake["paseo_id"] == "p"
    assert wake["agent_id"] == "a"
    assert wake["runner_endpoint"] == "endpoint"
    assert binding.extra["future_field"] == {"preserve": True}
    assert (
        addresses.resolve_reader(
            "h", "self", None, ReaderContext(env_address="automatic"), NOW
        )
        == "automatic"
    )
    assert (
        addresses.resolve_reader(
            "h", "boss", None, ReaderContext(env_address="main"), NOW
        )
        == "main"
    )


def test_refresh_requires_identity_current_binding_and_material_change(
    addresses: AddressRepository,
) -> None:
    marker = addresses.issue("worker", now=NOW)
    assert addresses.redeem(marker, "s", "h", CTX, now=NOW)
    version = addresses.version()
    assert not addresses.refresh_current(
        "h", "s", ReaderContext(cwd="/other"), NOW + timedelta(seconds=60)
    )
    assert addresses.version() == version
    context = ReaderContext(cwd="/new", paseo_id="p")
    assert addresses.refresh_current("h", "s", context, NOW + timedelta(seconds=60))
    version = addresses.version()
    assert addresses.refresh_current("h", "s", context, NOW + timedelta(seconds=61))
    assert addresses.version() == version
    assert addresses.unbind("s", NOW + timedelta(seconds=62))
    assert not addresses.refresh_current(
        "h", "s", context, NOW + timedelta(seconds=120)
    )


@pytest.mark.parametrize(
    "selector",
    [
        pytest.param("h-" + hashlib.sha256(b"s").hexdigest(), id="session-key"),
        pytest.param("s", id="session-id"),
        pytest.param("worker", id="address"),
    ],
)
def test_unbind_selectors_and_token_invalidation(
    addresses: AddressRepository, selector: str
) -> None:
    marker = addresses.issue("worker", now=NOW)
    assert addresses.redeem(marker, "s", "h", CTX, now=NOW)
    assert addresses.unbind(selector, NOW)
    assert addresses.current_token("worker") is None
    assert addresses.current_binding("worker") is None
    assert addresses.marker_error(marker, NOW) == "marker already used"


def test_binding_reads_order_live_window_and_unknown_extra_round_trip(
    addresses: AddressRepository,
) -> None:
    for name in ("zeta", "alpha"):
        marker = addresses.issue(name, now=NOW)
        assert addresses.redeem(
            marker, name, "h", ReaderContext(cwd=f"/{name}", paseo_id="p"), now=NOW
        )
    assert [binding.address for binding in addresses.list_bindings()] == [
        "alpha",
        "zeta",
    ]
    assert addresses.live_addresses(NOW + timedelta(minutes=29)) == {"alpha", "zeta"}
    assert addresses.live_addresses(NOW + timedelta(minutes=30)) == set()
    before = addresses.version()
    addresses.refresh_current(
        "h", "alpha", ReaderContext(cwd="/alpha", paseo_id="p"), NOW
    )
    assert addresses.current_binding("alpha").extra["wake_context"]["paseo_id"] == "p"  # type: ignore[union-attr,index]
    assert addresses.version() == before


def test_wake_state_requires_current_binding_and_uses_context(
    addresses: AddressRepository,
) -> None:
    addresses.mark_wake_gone("unbound", NOW)
    assert addresses.version().value == 0
    marker = addresses.issue("worker", now=NOW)
    assert addresses.redeem(
        marker, "s", "h", ReaderContext(cwd="/", paseo_id="p"), now=NOW
    )
    addresses.mark_wake_gone("worker", NOW)
    wake = addresses.wake_of("worker")
    assert wake == {"harness": "h", "session_id": "s", "cwd": "/", "paseo_id": "p"}
    context = ReaderContext(cwd="/", paseo_id="p")
    assert (
        addresses.resolve_reader("h", "s", None, context, NOW + timedelta(seconds=1))
        == "worker"
    )
    binding = addresses.current_binding("worker")
    assert binding is not None
    assert binding.extra["wake"] == "active"
    assert binding.extra["wake_cleared_at"] == "2026-01-01T00:00:01Z"


def test_slot_alias_order_validation_and_add_remove(
    addresses: AddressRepository,
) -> None:
    addresses.add_alias("slot-a", "plan-a")
    addresses.add_alias("slot-a", "plan-b")
    assert addresses.slots()[0].aliases == ("plan-a", "plan-b")
    assert addresses.resolve_alias("plan-a") == "slot-a"
    assert addresses.reader_addresses("plan-a") == {"slot-a", "plan-a", "plan-b"}
    addresses.remove_alias("plan-a")
    assert addresses.resolve_alias("plan-a") == "plan-a"
    with pytest.raises(ValueError):
        addresses.add_alias("bad slot")


def test_lease_busy_confirming_prompt_rewrite_and_shrink(
    addresses: AddressRepository,
    require_relay_storage: None,
) -> None:
    candidate = {
        "to": "reader",
        "message_ids": ["m1"],
        "prompt": "[varde-delivery: pending reader]",
    }
    first = addresses.lease_actions((candidate,), "t", NOW)[0]
    assert first.payload["message_ids"] == ("m1",)
    prompt = first.payload["prompt"]
    assert isinstance(prompt, str)
    assert f"[varde-delivery: {first.action_id} " in prompt
    assert (
        addresses.begin_confirm(first.action_id, "pushed", NOW).status
        is ConfirmStatus.BEGUN
    )
    assert first.action_id in {
        action.action_id for action in addresses.relay_snapshot().leases
    }
    assert (
        addresses.lease_actions(({"to": "reader", "message_ids": ["m1"]},), "t", NOW)
        == ()
    )
    second = addresses.lease_actions(
        ({"to": "reader", "message_ids": ["m2", "m3"]},), "t", NOW
    )[0]
    addresses.finish_confirm(
        first.action_id, "pushed", NOW, ("m1",), (("m2", "reader"),)
    )
    shrunk = addresses.action(second.action_id)
    assert shrunk is not None
    assert shrunk.message_ids == ("m3",)
    assert addresses.action(first.action_id).status == "confirmed"  # type: ignore[union-attr]
    third = addresses.lease_actions(
        ({"to": "reader", "message_ids": ["m4"]},), "t", NOW
    )[0]
    fourth = addresses.lease_actions(
        ({"to": "other-reader", "message_ids": ["m5"]},), "t", NOW
    )[0]
    addresses.finish_confirm(
        third.action_id, "pushed", NOW, ("m4",), (("m5", "other-reader"),)
    )
    assert addresses.action(fourth.action_id).status == "superseded"  # type: ignore[union-attr]


def test_confirm_unknown_result_resume_and_attempt_dedupe(
    addresses: AddressRepository,
    require_relay_storage: None,
) -> None:
    assert (
        addresses.begin_confirm("missing", "failed", NOW).status
        is ConfirmStatus.UNKNOWN
    )
    assert addresses.relay_snapshot().events[-1]["event"] == "unknown-confirm"
    action = addresses.lease_actions(({"to": "r", "message_ids": ["m"]},), "t", NOW)[0]
    with pytest.raises(ValueError):
        addresses.begin_confirm(action.action_id, "bad", NOW)
    addresses.begin_confirm(action.action_id, "failed", NOW)
    resume = addresses.begin_confirm(action.action_id, "pushed", NOW)
    assert resume.status is ConfirmStatus.RESUME and resume.result == "failed"
    addresses.finish_confirm(action.action_id, "failed", NOW, ("m",), ())
    addresses.finish_confirm(action.action_id, "failed", NOW, ("m",), ())
    assert len(addresses.relay_snapshot().attempts["m"]) == 1


def test_renew_event_trimming_sleep_and_send_liveness_cap(
    addresses: AddressRepository,
    require_relay_storage: None,
) -> None:
    action = addresses.lease_actions(({"to": "r", "message_ids": ["m"]},), "t", NOW)[0]
    addresses.begin_confirm(action.action_id, "failed", NOW)
    stored_action = addresses.action(action.action_id)
    assert stored_action is not None
    expiry = stored_action.expires_at
    addresses.record_event(
        "slept", now=NOW - timedelta(days=2), data={"gap_seconds": 50}
    )
    stored_action = addresses.action(action.action_id)
    assert stored_action is not None
    assert stored_action.expires_at == expiry + timedelta(seconds=50)
    addresses.record_event("slept", now=NOW, data={"gap_seconds": 2})
    assert (
        sum(row["event"] == "slept" for row in addresses.relay_snapshot().events) == 1
    )
    for i in range(205):
        addresses.record_send_liveness(f"m-{i}", "r", NOW)
    rows = [
        row
        for row in addresses.relay_snapshot().events
        if row["event"] == "send-liveness"
    ]
    assert len(rows) == 200
    addresses.record_send_liveness("fresh", "r", NOW + timedelta(days=4))
    assert [
        row["message_id"]
        for row in addresses.relay_snapshot().events
        if row["event"] == "send-liveness"
    ] == ["fresh"]


def test_liveness_return_cycles_and_sleep_adjusted_age(
    addresses: AddressRepository,
    require_relay_storage: None,
) -> None:
    addresses.heartbeat("t", "waiting", NOW, instance_id="instance-1")
    assert addresses.mailman_alive("t", NOW + timedelta(seconds=89))
    assert not addresses.mailman_alive("t", NOW + timedelta(seconds=90))
    addresses.record_event(
        "slept", now=NOW + timedelta(seconds=30), data={"gap_seconds": 60}
    )
    assert addresses.mailman_alive("t", NOW + timedelta(seconds=90))
    expect = NOW + timedelta(minutes=9)
    assert addresses.return_mailman(
        "t",
        expect,
        expect,
        instance_id="instance-1",
        completed=True,
        reached_deadline=True,
    )
    assert addresses.relay_snapshot().cycles["t"] == 1
    addresses.end("t", expect + timedelta(seconds=1), instance_id="instance-1")
    assert not addresses.mailman_alive("t", expect + timedelta(seconds=1))


def test_heartbeat_if_waiting_requires_current_waiting_token(
    addresses: AddressRepository,
    require_relay_storage: None,
) -> None:
    addresses.heartbeat("t", "waiting", NOW, instance_id="instance-1")

    assert addresses.heartbeat_if_waiting(
        "t",
        NOW + timedelta(seconds=30),
        instance_id="instance-1",
    )
    snapshot = addresses.relay_snapshot()
    latest = next(
        row for row in reversed(snapshot.events) if row.get("token_id") == "t"
    )
    assert latest["at"] == "2026-01-01T00:00:30Z"

    addresses.end("t", NOW + timedelta(seconds=31), instance_id="instance-1")
    before = addresses.relay_snapshot()
    assert not addresses.heartbeat_if_waiting(
        "t",
        NOW + timedelta(seconds=60),
        instance_id="instance-1",
    )
    assert addresses.relay_snapshot().events == before.events


def test_retire_reservations_wakes_and_version_changes(
    addresses: AddressRepository,
    require_relay_storage: None,
) -> None:
    before = addresses.version()
    assert addresses.reserve_escalation("m", "escalated", NOW)
    assert addresses.version() != before
    assert addresses.relay_snapshot().escalations["m"]["outcome"] == "escalated"
    assert not addresses.reserve_escalation("m", "dropped", NOW)
    assert addresses.reserve_suspect("m:a", NOW)
    assert not addresses.reserve_suspect("m:a", NOW)
    before = addresses.version()
    addresses.retire(("a",), ("t",), NOW)
    assert addresses.version() != before
    before = addresses.version()
    addresses.retire(("a",), ("t",), NOW)
    assert addresses.version() != before
    assert addresses.retired().addresses == {"a"}
    assert addresses.retired_records() == {
        "a": "2026-01-01T00:00:00Z",
        "mailman:t": "2026-01-01T00:00:00Z",
    }
    before = addresses.version()
    addresses.touch_wake()
    assert addresses.version() != before
    assert addresses.wake_token().value != 0


def test_pure_reads_do_not_advance_version(
    addresses: AddressRepository, require_relay_storage: None
) -> None:
    addresses.add_alias("slot", "alias")
    version = addresses.version()
    addresses.list_bindings()
    addresses.live_addresses(NOW)
    addresses.current_binding("slot")
    addresses.current_token("slot")
    addresses.wake_of("slot")
    addresses.events()
    addresses.last_refusal("slot")
    addresses.slots()
    addresses.resolve_alias("alias")
    addresses.reader_addresses("alias")
    addresses.relay_snapshot()
    addresses.action("absent")
    addresses.retired()
    addresses.wake_token()
    addresses.version()
    assert addresses.version() == version


def test_every_repository_write_advances_version(
    addresses: AddressRepository, require_relay_storage: None
) -> None:
    def changed(call: Any) -> Any:
        before = addresses.version()
        result = call()
        assert addresses.version() != before
        return result

    marker = changed(lambda: addresses.issue("worker", now=NOW))
    changed(lambda: addresses.redeem(marker, "s", "h", CTX, now=NOW))
    changed(
        lambda: addresses.refresh_current(
            "h",
            "s",
            ReaderContext(cwd="/new", paseo_id="p"),
            NOW + timedelta(seconds=60),
        )
    )
    changed(lambda: addresses.mark_wake_gone("worker", NOW))
    changed(lambda: addresses.clear_wake_gone("worker", NOW + timedelta(seconds=1)))
    changed(lambda: addresses.unbind("worker", NOW + timedelta(seconds=2)))
    changed(lambda: addresses.add_alias("slot", "alias"))
    changed(lambda: addresses.remove_alias("alias"))
    changed(lambda: addresses.record_event("waiting", now=NOW, data={"token_id": "t"}))
    changed(lambda: addresses.record_send_liveness("m", "r", NOW))
    action = changed(
        lambda: addresses.lease_actions(({"to": "r", "message_ids": ["m"]},), "t", NOW)
    )[0]
    changed(lambda: addresses.begin_confirm(action.action_id, "failed", NOW))
    changed(
        lambda: addresses.finish_confirm(action.action_id, "failed", NOW, ("m",), ())
    )
    renewed = changed(
        lambda: addresses.lease_actions(({"to": "r", "message_ids": ["n"]},), "t", NOW)
    )[0]
    changed(lambda: addresses.renew(renewed.action_id, NOW))
    changed(lambda: addresses.heartbeat("t", "waiting", NOW, instance_id="i"))
    changed(
        lambda: addresses.return_mailman(
            "t", NOW, NOW, instance_id="i", completed=True, reached_deadline=True
        )
    )
    changed(lambda: addresses.end("t", NOW, instance_id="i"))
    changed(lambda: addresses.reserve_escalation("m", "escalated", NOW))
    changed(lambda: addresses.reserve_suspect("m:a", NOW))
    changed(lambda: addresses.retire(("a",), ("t",), NOW))
    changed(addresses.touch_wake)
    invalid = "[varde-address: worker vt1.AAAAAAAAAAAAAAAAAAAAAAAAAA]"
    assert not changed(lambda: addresses.redeem(invalid, "x", "h", CTX, now=NOW))


def test_event_log_is_append_only_and_read_capability(
    address_backend: BackendRegistration,
    addresses: AddressRepository,
    require_relay_storage: None,
) -> None:
    if not address_backend.capabilities.append_only_events:
        pytest.skip("backend does not advertise append-only event history")
    marker = addresses.issue("reader", now=NOW)
    assert addresses.redeem(marker, "session", "h", CTX, now=NOW)
    bind_event = addresses.events()[0]
    assert bind_event.event == "bind"
    assert bind_event.session_key == "h-" + hashlib.sha256(b"session").hexdigest()
    assert bind_event.at == NOW
    addresses.issue("another", now=NOW)
    assert addresses.events()[0] == bind_event
    addresses.record_event("one", now=NOW)
    first = addresses.relay_snapshot().events
    addresses.record_event("two", now=NOW)
    assert [row["event"] for row in first] == ["one"]
    assert [row["event"] for row in addresses.relay_snapshot().events] == ["one", "two"]


def _redeem_in_process(
    backend: str, working: str, marker: str, session: str, queue: Any
) -> None:
    repository = backend_registry()[backend].factory(Path(working))
    queue.put(repository.redeem(marker, session, "h", CTX, now=NOW))


def _mutate_in_process(
    backend: str, working: str, case: str, index: int, barrier: Any, queue: Any
) -> None:
    repository = backend_registry()[backend].factory(Path(working))
    barrier.wait(10)
    if case == "alias":
        if index == 8:
            repository.remove_alias("remove-me")
        else:
            repository.add_alias("slot", f"a{index}")
        queue.put(True)
    else:
        actions = repository.lease_actions(
            ({"to": "r", "message_ids": ["m"]},), "t", NOW
        )
        queue.put(len(actions))


def _issue_or_redeem_in_process(
    backend: str,
    working: str,
    operation: str,
    marker: str,
    barrier: Any,
    queue: Any,
) -> None:
    repository = backend_registry()[backend].factory(Path(working))
    barrier.wait(10)
    if operation == "issue":
        repository.issue("reader", supersede=True, now=NOW + timedelta(seconds=1))
        queue.put(True)
    else:
        queue.put(repository.redeem(marker, "session", "h", CTX, now=NOW))


@pytest.mark.parametrize("case", ("redeem", "issue-redeem", "alias", "lease"))
@pytest.mark.parametrize("backend_name", tuple(backend_registry()))
def test_cross_process_cases_are_capability_gated(
    case: str, backend_name: str, tmp_path: Path
) -> None:
    registration = backend_registry()[backend_name]
    if case == "lease" and not registration.capabilities.relay_storage:
        pytest.skip(f"{backend_name} backend does not implement relay storage")
    if not registration.capabilities.multi_process:
        pytest.skip(f"{backend_name} backend is not shared between processes")
    repository = registration.factory(tmp_path)
    if case == "redeem":
        marker = repository.issue("reader", now=NOW)
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        processes = [
            context.Process(
                target=_redeem_in_process,
                args=(backend_name, str(tmp_path), marker, f"s{i}", queue),
            )
            for i in range(6)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(30)
            assert process.exitcode == 0
        assert sum(queue.get(timeout=2) for _ in processes) == 1
    elif case == "issue-redeem":
        marker = repository.issue("reader", now=NOW)
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(2)
        queue = context.Queue()
        processes = [
            context.Process(
                target=_issue_or_redeem_in_process,
                args=(backend_name, str(tmp_path), operation, marker, barrier, queue),
            )
            for operation in ("issue", "redeem")
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(30)
            assert process.exitcode == 0
        assert all(queue.get(timeout=2) for _ in processes)
        assert len(repository.list_bindings()) == 1
        assert sum(event.event == "bind" for event in repository.events()) == 1
    elif case == "alias":
        repository.add_alias("slot", "remove-me")
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(9)
        queue = context.Queue()
        processes = [
            context.Process(
                target=_mutate_in_process,
                args=(backend_name, str(tmp_path), case, i, barrier, queue),
            )
            for i in range(9)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(30)
            assert process.exitcode == 0
        assert sum(queue.get(timeout=2) for _ in processes) == 9
        assert repository.reader_addresses("slot") == {
            "slot",
            *(f"a{i}" for i in range(8)),
        }
    else:
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(8)
        queue = context.Queue()
        processes = [
            context.Process(
                target=_mutate_in_process,
                args=(backend_name, str(tmp_path), case, i, barrier, queue),
            )
            for i in range(8)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(30)
            assert process.exitcode == 0
        assert sum(queue.get(timeout=2) for _ in processes) == 1


def test_registry_import_failures_are_loud_for_files_and_sqlite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib
    import importlib.util

    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(ImportError(name)),
    )
    with pytest.raises(ImportError, match="varde_data.backends.files.addresses"):
        backend_registry()
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: None if name.endswith("files.addresses") else object(),
    )
    with pytest.raises(ImportError, match="sqlite_addresses"):
        backend_registry()


def test_registry_does_not_hide_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util

    def missing_dependency(_name: str) -> object:
        raise ModuleNotFoundError("missing dependency", name="dependency")

    monkeypatch.setattr(importlib.util, "find_spec", missing_dependency)
    with pytest.raises(ModuleNotFoundError, match="missing dependency"):
        backend_registry()


def test_capability_flags_are_consumed(address_backend: BackendRegistration) -> None:
    flags = address_backend.capabilities
    assert all(
        isinstance(value, bool)
        for value in (
            flags.multi_process,
            flags.lock_timeout,
            flags.append_only_events,
            flags.lock_free_reads,
            flags.relay_storage,
        )
    )


@pytest.mark.parametrize("backend_name", tuple(backend_registry()))
def test_held_lock_behavior_is_deferred_to_backend_lock_suites(
    backend_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration = backend_registry()[backend_name]
    if not registration.capabilities.lock_timeout:
        pytest.skip(f"{backend_name} does not have shared process locks")
    if backend_name != "files":
        pytest.skip("held-lock timeout is checked by the backend's own suite")
    import varde_data.backends.files.addresses_bindings as address_files

    original = address_files.file_lock

    def short_lock(path: Path, *, timeout: float):
        return original(path, timeout=min(timeout, 0.05))

    monkeypatch.setattr(address_files, "file_lock", short_lock)
    lock = tmp_path / ".cache/inbox/addresses/worker/.lock"
    repository = registration.factory(tmp_path)
    with file_lock(lock, timeout=1), pytest.raises(Locked):
        repository.issue("worker", now=NOW)
