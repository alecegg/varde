from __future__ import annotations

import hashlib
import inspect
import json
import multiprocessing
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import get_type_hints

import pytest
from messages_backends import AliasResolver, BackendRegistration, backend_registry
from varde_data.backends.files.messages import FilesMessages
from varde_data.errors import Invalid, NotFound
from varde_data.records.messages import (
    Delivery,
    DeliveryOutcome,
    Message,
    NewMessage,
    NoteRef,
    RelayEvent,
)
from varde_data.repos.messages import (
    MessageRepository,
    parse_messages,
    validate_message,
)
from varde_data.version import Cursor


@pytest.fixture(params=tuple(backend_registry()), ids=tuple(backend_registry()))
def message_backend(request: pytest.FixtureRequest) -> BackendRegistration:
    return backend_registry()[request.param]


@pytest.fixture
def working(tmp_path: Path) -> Path:
    return tmp_path / "working"


@pytest.fixture
def messages(message_backend: BackendRegistration, working: Path) -> MessageRepository:
    return message_backend.factory(working, AliasResolver())


def _new(
    text: str = "hello", *, to: str = "alias-a", from_: str = "sender"
) -> NewMessage:
    return NewMessage(from_, to, "info", text, ts="2026-01-01T00:00:00Z")


def _record(
    message_id: str,
    to: str,
    *,
    text: str = "old",
) -> Message:
    return Message("2026-01-01T00:00:00Z", "sender", to, "info", text, id=message_id)


def _record_no_id(to: str) -> Message:
    return Message("2026-01-01T00:00:00Z", "sender", to, "info", "no id")


def _wire_size(message: NewMessage, *, include_id: bool) -> int:
    fields = {
        "ts": message.ts,
        "from": message.from_,
        "to": message.to,
        "kind": message.kind,
        "text": message.text,
    }
    if message.notes is not None:
        fields["notes"] = message.notes
    if include_id:
        fields["id"] = "m-00000000"
    encoded = json.dumps(fields, ensure_ascii=False, separators=(",", ":")).encode()
    return len(encoded) + 1


def _message_at_wire_size(size: int, *, include_id: bool) -> NewMessage:
    for note_size in range(size):
        message = NewMessage(
            "sender",
            "reader",
            "info",
            "x",
            notes="n" * note_size,
            ts="2026-01-01T00:00:00Z",
        )
        if _wire_size(message, include_id=include_id) == size:
            return message
    raise AssertionError(f"no note length produced a {size}-byte row")


def test_validation_contract() -> None:
    for message in (
        NewMessage("bad address", "reader", "info", "hello"),
        NewMessage("sender", "reader", "unknown", "hello"),
        NewMessage("sender", "reader", "info", ""),
        NewMessage("sender", "reader", "info", "two\nlines"),
        NewMessage("sender", "reader", "info", "x" * 301),
        NewMessage("sender", "reader", "info", "😀" * 300),
    ):
        with pytest.raises(Invalid):
            validate_message(message)
    validate_message(_new("x" * 300))


def test_append_checks_encoded_limit_with_id_and_does_not_store_invalid(
    messages: MessageRepository,
) -> None:
    exact_without_id = _message_at_wire_size(1_000, include_id=False)
    just_under_with_id = _message_at_wire_size(999, include_id=True)

    with pytest.raises(Invalid):
        messages.append(exact_without_id)
    assert messages.read_all().records == ()
    stored = messages.append(just_under_with_id)
    assert stored.id is not None


@pytest.mark.parametrize("text", ("\u0085", "\u2028", "\u2029", "\x00"))
def test_validation_allows_non_cr_lf_controls_and_separators(text: str) -> None:
    validate_message(_new(text))


def test_append_order_cursor_order_and_immutable_records(
    messages: MessageRepository,
) -> None:
    first = messages.append(_new("first"))
    middle = messages.head()
    second = messages.append(_new("second", to="slot-a"))
    third = messages.append(_new("third"))

    assert [record.text for record in messages.read_all().records] == [
        "first",
        "second",
        "third",
    ]
    assert messages.read_since(Cursor("0")).records[0] == first
    assert messages.read_since(middle).records == (second, third)
    assert messages.head() > middle
    assert first.text == "first"


def test_status_events_read_is_backend_neutral(messages: MessageRepository) -> None:
    assert messages.status_events() == ()


def test_claim_advances_reader_cursor_on_every_backend(
    messages: MessageRepository,
    message_backend: BackendRegistration,
    working: Path,
) -> None:
    message = messages.append(_new())
    messages.register_reader("alias-a", from_start=True)
    assert messages.claim_unread("alias-a", "session", "hook", "t") == (message,)
    assert messages.reader_position("slot-a") == message.id

    if message_backend.name == "sqlite":
        from varde_data.messages import messages_db_path

        with closing(sqlite3.connect(messages_db_path(working))) as db:
            row = db.execute(
                "SELECT position FROM cursor_positions WHERE reader='slot-a'"
            ).fetchone()
        assert row is not None and row[0] == 1


def test_legacy_offset_id_fixture_skips_bad_rows_and_tolerates_torn_tail() -> None:
    row = json.dumps(
        {"ts": "t", "from": "a", "to": "b", "kind": "info", "text": "x"},
        separators=(",", ":"),
    ).encode()
    prefix = b"{bad}\n"
    parsed = parse_messages(prefix + row + b"\n" + b"{torn")
    expected = "m-" + hashlib.sha256(str(len(prefix)).encode() + row).hexdigest()[:8]
    assert parsed.records[0].id == expected
    assert parsed.records[0].legacy_id == expected
    assert len(parsed.skipped) == 1


def test_legacy_id_parser_uses_lf_readline_with_lone_cr() -> None:
    row = json.dumps(
        {"ts": "t", "from": "a", "to": "b", "kind": "info", "text": "x"},
        separators=(",", ":"),
    ).encode()
    malformed_with_lone_cr = b"{bad\r}\n"
    data = malformed_with_lone_cr + row + b"\n"
    parsed = parse_messages(data)
    second_offset = len(malformed_with_lone_cr)
    expected = "m-" + hashlib.sha256(str(second_offset).encode() + row).hexdigest()[:8]
    assert len(parsed.skipped) == 1
    assert parsed.records[0].legacy_id == expected


def test_claim_is_idempotent_and_exclusive_across_readers(
    messages: MessageRepository,
) -> None:
    sent = messages.append(_new())
    first = messages.claim_unread("alias-a", "session-1", "hook", "t1")
    second = messages.claim_unread("slot-a", "session-2", "hook", "t2")

    assert first == (sent,)
    assert second == ()
    assert messages.unread("alias-a") == ()


def test_single_and_multi_address_readers_scan_from_start(
    messages: MessageRepository,
) -> None:
    single = messages.import_messages((_record("m-00000001", "solo"),))[0]
    multi = messages.import_messages((_record("m-00000002", "alias-a"),))[0]
    messages.register_reader("solo", from_start=False)
    messages.register_reader("slot-a", from_start=False)

    assert messages.peek_unread("solo") == (single,)
    assert messages.peek_unread("slot-a") == (multi,)
    assert single in messages.peek_unread("solo")
    assert messages.pending_by_address() == {
        "solo": (single,),
        "alias-a": (multi,),
    }
    assert messages.status().lag == 2


def test_peek_without_index_reads_from_start_without_registering(
    messages: MessageRepository,
) -> None:
    imported = messages.import_messages((_record("m-00000001", "solo"),))[0]
    before = messages.version()

    assert messages.peek_unread("solo") == (imported,)
    assert messages.version() == before


def test_import_preserves_raw_legacy_rows_and_deduplicates_by_id(
    messages: MessageRepository,
) -> None:
    legacy = {
        "ts": "2026-01-01T00:00:00Z",
        "from": "sender",
        "to": "reader",
        "kind": "info",
        "text": "migrated",
        "id": "m-00000009",
        "legacy": True,
    }
    malformed = {"id": "m-0000000a", "text": "preserve raw"}

    assert messages.import_messages((legacy, malformed, legacy)) == (
        legacy,
        malformed,
    )
    assert messages.message_ids() == {"m-00000009", "m-0000000a"}
    assert messages.read_all().records == (
        Message(
            "2026-01-01T00:00:00Z",
            "sender",
            "reader",
            "info",
            "migrated",
            id="m-00000009",
        ),
    )
    assert messages.import_messages((malformed,)) == ()


def test_alias_resolution_and_ack_use_resolved_reader(
    messages: MessageRepository,
) -> None:
    sent = messages.append(_new(to="alias-a"))
    assert messages.unread("slot-a") == (sent,)
    delivery = Delivery(sent.id or "", "slot-a", "s", "cli", "delivered", "t")
    assert messages.record_delivery(delivery) is DeliveryOutcome.RECORDED
    assert messages.ack("alias-a", sent.id or "", now="t")
    assert messages.unread("slot-a") == ()


def test_relay_event_preserves_adapter_metadata(
    messages: MessageRepository,
) -> None:
    event = RelayEvent(
        "m-deadbeef",
        "reader",
        "pushed",
        "now",
        action_created_at="created",
        details={"action_id": "action", "token_id": "mailman", "harness": "claude"},
    )

    assert messages.record_relay_event(event) is DeliveryOutcome.RECORDED
    delivery = messages.deliveries()[0]
    assert delivery.details == event.details
    assert delivery.action_created_at == "created"


def test_files_delivery_read_rejects_malformed_log(working: Path) -> None:
    from varde_data.errors import Invalid

    delivery_log = working / ".cache" / "inbox" / "deliveries.jsonl"
    delivery_log.parent.mkdir(parents=True)
    delivery_log.write_text("not json\n")

    with pytest.raises(Invalid, match="invalid delivery log row"):
        FilesMessages(working).deliveries()


def test_files_status_events_read_complete_object_rows(working: Path) -> None:
    path = working / ".cache" / "inbox" / "events.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"event":"pushed"}\nnot-json\n', encoding="utf-8")

    assert FilesMessages(working).status_events() == ({"event": "pushed"},)


def test_ack_requires_delivery_and_rejects_other_reader(
    messages: MessageRepository,
) -> None:
    sent = messages.append(_new())
    with pytest.raises(Invalid):
        messages.ack("alias-a", sent.id or "")
    with pytest.raises((Invalid, NotFound)):
        messages.ack("other", sent.id or "")
    with pytest.raises(Invalid, match="message id"):
        messages.ack("alias-a", "invalid-id")


def test_append_preserves_reply_to(messages: MessageRepository) -> None:
    message = messages.append(
        NewMessage("sender", "alias-a", "info", "answer", reply_to="m-12345678")
    )

    assert message.reply_to == "m-12345678"
    assert messages.read_all().records[-1].reply_to == "m-12345678"


def test_delivered_matching_uses_resolved_reader(messages: MessageRepository) -> None:
    sent = messages.append(_new(to="alias-a"))
    for reader in ("slot-a", "alias-a"):
        outcome = messages.record_delivery(
            Delivery(sent.id or "", reader, "s", "relay", "delivered", "t")
        )
    assert outcome is DeliveryOutcome.DUPLICATE
    assert messages.unread("slot-a") == ()

    other = messages.append(_new(to="alias-a", text="other"))
    skipped = messages.record_delivery(
        Delivery(other.id or "", "different-reader", "s", "relay", "delivered", "t")
    )
    assert skipped is DeliveryOutcome.SKIPPED


def test_relay_delivered_records_without_message_existence_check(
    messages: MessageRepository,
) -> None:
    event = RelayEvent("m-deadbeef", "some-reader", "delivered", "now")
    assert messages.record_relay_event(event) is DeliveryOutcome.RECORDED
    assert messages.record_relay_event(event) is DeliveryOutcome.DUPLICATE


def test_relay_failure_reason_persists_every_backend(
    messages: MessageRepository,
) -> None:
    message = messages.append(_new())
    assert (
        messages.record_relay_event(
            RelayEvent(
                message.id or "",
                "slot-a",
                "failed",
                "now",
                reason="provider timeout",
            )
        )
        is DeliveryOutcome.RECORDED
    )

    delivery = messages.deliveries()[0]
    assert delivery.reason == "provider timeout"


def test_relay_event_action_order_and_pair_scope(
    messages: MessageRepository,
) -> None:
    first = messages.append(_new())
    second = messages.append(_new(text="second"))

    def relay(
        message_id: str,
        reader: str = "slot-a",
        action_created_at: str | None = "2026-01-02T00:00:00Z",
    ) -> DeliveryOutcome:
        return messages.record_relay_event(
            RelayEvent(
                message_id,
                reader,
                "pushed",
                "now",
                action_created_at=action_created_at,
            )
        )

    assert relay(first.id or "") is DeliveryOutcome.RECORDED
    assert relay(first.id or "") is DeliveryOutcome.DUPLICATE
    assert (
        relay(first.id or "", action_created_at="2026-01-01T00:00:00Z")
        is DeliveryOutcome.DUPLICATE
    )
    assert relay(first.id or "", action_created_at=None) is DeliveryOutcome.DUPLICATE
    without_previous_action = messages.record_relay_event(
        RelayEvent(
            second.id or "",
            "slot-a",
            "failed",
            "now",
            action_created_at=None,
        )
    )
    assert without_previous_action is DeliveryOutcome.RECORDED
    assert (
        messages.record_relay_event(
            RelayEvent(
                second.id or "",
                "slot-a",
                "failed",
                "now",
                action_created_at="2026-01-03T00:00:00Z",
            )
        )
        is DeliveryOutcome.DUPLICATE
    )
    assert relay(first.id or "", reader="different-reader") is DeliveryOutcome.RECORDED
    assert relay(second.id or "", reader="another-reader") is DeliveryOutcome.RECORDED
    parameters = inspect.signature(messages.record_relay_event).parameters.values()
    assert all(item.kind is not inspect.Parameter.VAR_KEYWORD for item in parameters)
    assert {item.name for item in parameters} == {"event"}
    assert {item.name for item in RelayEvent.__dataclass_fields__.values()} == {
        "message_id",
        "reader",
        "event",
        "now",
        "session",
        "via",
        "action_created_at",
        "reason",
        "details",
    }


def test_concluded_read_and_write_are_backend_neutral(
    messages: MessageRepository,
) -> None:
    before = messages.version()
    assert messages.concluded_addresses() == set()
    assert messages.version() == before
    messages.mark_concluded("new-address")
    assert "new-address" in messages.concluded_addresses()


def test_import_preserves_message_fields_and_note_ref_is_opaque(
    messages: MessageRepository,
) -> None:
    imported = _record("m-12345678", "solo", text="preserve me")
    before = messages.version()
    assert messages.import_messages((imported, imported)) == (imported,)
    assert messages.version() != before
    assert messages.read_all().records == (imported,)
    after_import = messages.version()
    assert messages.import_messages((imported,)) == ()
    assert messages.version() == after_import
    with pytest.raises(Invalid, match="require an id"):
        messages.import_messages((_record_no_id("solo"),))
    assert messages.version() == after_import
    assert get_type_hints(messages.read_note)["ref"] is NoteRef
    with pytest.raises(NotFound):
        messages.read_note(NoteRef("opaque-1"))


def test_read_methods_never_write(messages: MessageRepository) -> None:
    messages.append(_new())
    before = messages.version()
    head = messages.head()
    messages.read_since(Cursor("0"))
    messages.read_all()
    messages.peek_unread("solo")
    messages.status()
    messages.version()
    messages.concluded_addresses()
    messages.deliveries()
    messages.pending_by_address()
    assert messages.head() == head
    assert messages.version() == before
    status = messages.status()
    assert isinstance(status.diagnostics, Mapping)
    assert not hasattr(status, "below_watermark")
    assert not hasattr(status, "stray_stores")


def test_pending_by_address_and_acked_status_are_separate(
    messages: MessageRepository,
) -> None:
    sent = messages.append(_new(to="alias-a"))
    assert messages.pending_by_address() == {"alias-a": (sent,)}
    assert (
        messages.record_delivery(
            Delivery(sent.id or "", "slot-a", "s", "cli", "delivered", "t")
        )
        is DeliveryOutcome.RECORDED
    )
    assert messages.pending_by_address() == {}
    assert messages.ack("alias-a", sent.id or "", now="t")
    assert messages.status().acked == (sent.id,)


def test_pending_by_address_ignores_reader_cursor(
    messages: MessageRepository,
) -> None:
    sent = messages.import_messages((_record("m-00000011", "solo"),))[0]
    messages.register_reader("solo", from_start=False)
    assert messages.peek_unread("solo") == (sent,)
    assert messages.pending_by_address() == {"solo": (sent,)}


def test_relay_order_accepts_incoming_action_when_prior_has_none(
    messages: MessageRepository,
) -> None:
    sent = messages.append(_new())
    assert (
        messages.record_relay_event(RelayEvent(sent.id or "", "slot-a", "failed", "t"))
        is DeliveryOutcome.RECORDED
    )
    assert (
        messages.record_relay_event(
            RelayEvent(
                sent.id or "", "slot-a", "failed", "t2", action_created_at="later"
            )
        )
        is DeliveryOutcome.DUPLICATE
    )


def test_registry_exposes_backend_capabilities(
    message_backend: BackendRegistration,
) -> None:
    capabilities = message_backend.capabilities
    assert isinstance(capabilities.torn_tail, bool)
    assert isinstance(capabilities.byte_cursor, bool)
    assert isinstance(capabilities.shared_processes, bool)
    assert isinstance(capabilities.append_only, bool)


def test_registry_does_not_hide_present_backend_import_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib
    import importlib.util

    def present(_: str) -> object:
        return object()

    def failed_import(name: str) -> object:
        raise ImportError(f"broken backend: {name}")

    monkeypatch.setattr(importlib.util, "find_spec", present)
    monkeypatch.setattr(importlib, "import_module", failed_import)
    with pytest.raises(ImportError, match="broken backend: varde_data.messages"):
        backend_registry()


def test_torn_tail_is_ignored_by_backends_that_support_it(
    message_backend: BackendRegistration,
    messages: MessageRepository,
    working: Path,
) -> None:
    if not message_backend.capabilities.torn_tail:
        pytest.skip("backend does not store a torn message tail")
    if message_backend.seed_raw_messages is None:
        pytest.fail("torn-tail capability requires a raw-message test seeder")
    valid = json.dumps(
        {
            "ts": "t",
            "from": "sender",
            "to": "reader",
            "kind": "info",
            "text": "complete",
            "id": "m-12345678",
        },
        separators=(",", ":"),
    ).encode()
    message_backend.seed_raw_messages(working, valid + b"\n{torn")
    result = messages.read_all()
    assert [message.id for message in result.records] == ["m-12345678"]
    assert result.skipped == ()


def test_byte_cursor_backend_reads_legacy_id_after_lone_cr(
    message_backend: BackendRegistration,
    messages: MessageRepository,
    working: Path,
) -> None:
    if not message_backend.capabilities.byte_cursor:
        pytest.skip("backend does not use byte cursors")
    if message_backend.seed_raw_messages is None:
        pytest.fail("byte-cursor capability requires a raw-message test seeder")
    row = json.dumps(
        {"ts": "t", "from": "a", "to": "b", "kind": "info", "text": "x"},
        separators=(",", ":"),
    ).encode()
    prefix = b"{bad\r}\n"
    message_backend.seed_raw_messages(working, prefix + row + b"\n")
    result = messages.read_all()
    expected = "m-" + hashlib.sha256(str(len(prefix)).encode() + row).hexdigest()[:8]
    assert result.records[0].legacy_id == expected


def test_append_only_contract_has_no_rewrite_and_preserves_existing_rows(
    message_backend: BackendRegistration,
    messages: MessageRepository,
) -> None:
    if not message_backend.capabilities.append_only:
        pytest.skip("backend does not advertise append-only messages")
    first = messages.append(_new("first"))
    second = messages.append(_new("second"))
    assert messages.read_all().records == (first, second)
    assert not hasattr(messages, "rewrite")
    delivered = Delivery(first.id or "", "slot-a", "s", "cli", "delivered", "t")
    assert messages.record_delivery(delivered) is DeliveryOutcome.RECORDED
    assert messages.read_all().records == (first, second)


def _append_from_process(backend_name: str, working: str) -> None:
    backend = backend_registry()[backend_name]
    messages = backend.factory(Path(working), AliasResolver())
    messages.append(_new("from process", to="alias-a"))


def test_shared_process_backends_share_appends(
    message_backend: BackendRegistration,
    messages: MessageRepository,
    working: Path,
) -> None:
    if not message_backend.capabilities.shared_processes:
        pytest.skip("backend does not share state across processes")
    process = multiprocessing.get_context("spawn").Process(
        target=_append_from_process,
        args=(message_backend.name, str(working)),
    )
    process.start()
    process.join(timeout=30)
    if process.is_alive():
        process.terminate()
        process.join()
        pytest.fail("message append process did not finish")
    assert process.exitcode == 0
    assert [message.text for message in messages.read_all().records] == ["from process"]


def test_every_write_changes_version_including_same_tick_rewrite(
    messages: MessageRepository,
) -> None:
    before = messages.version()
    first = messages.append(_new("same timestamp"))
    after_append = messages.version()
    assert after_append != before
    messages.append(_new("same timestamp"))
    after_same_tick_append = messages.version()
    assert after_same_tick_append != after_append

    assert (
        messages.record_delivery(
            Delivery(first.id or "", "slot-a", "s", "cli", "delivered", "t")
        )
        is DeliveryOutcome.RECORDED
    )
    after_delivery = messages.version()
    assert after_delivery != after_same_tick_append
    assert (
        messages.record_relay_event(
            RelayEvent(first.id or "", "slot-a", "pushed", "t", action_created_at="a")
        )
        is DeliveryOutcome.RECORDED
    )
    after_relay = messages.version()
    assert after_relay != after_delivery
    assert messages.ack("alias-a", first.id or "", now="t")
    after_ack = messages.version()
    assert after_ack != after_relay
    messages.register_reader("unregistered", from_start=True)
    after_register = messages.version()
    assert after_register != after_ack
    messages.commit_cursor("unregistered", messages.head())
    after_cursor = messages.version()
    assert after_cursor != after_register
    messages.mark_concluded("address")
    after_concluded = messages.version()
    assert after_concluded != after_cursor
    messages.mark_concluded("address")
    assert messages.version() != after_concluded


def test_files_version_excludes_relay_and_slots(
    message_backend: BackendRegistration, working: Path, messages: MessageRepository
) -> None:
    if message_backend.name != "files":
        pytest.skip("relay and slot files are files-backend concerns")
    state = working / ".cache" / "inbox" / "relay" / "state.json"
    state.parent.mkdir(parents=True)
    before = messages.version()
    state.write_text('{"concluded_addresses":[]}', encoding="utf-8")
    assert messages.version() == before
    state.write_text('{"concluded_addresses":["done"]}', encoding="utf-8")
    assert messages.version() == before

    slots = working / ".cache" / "inbox" / "slots" / "state.json"
    slots.parent.mkdir(parents=True)
    slots.write_text('{"address":"reader"}', encoding="utf-8")
    assert messages.version() == before


def test_message_parser_tolerates_torn_tail_and_reports_bad_complete_rows() -> None:
    bad = b"not-json\n"
    parsed = parse_messages(bad + b'{"ts":')
    assert parsed.records == ()
    assert len(parsed.skipped) == 1
