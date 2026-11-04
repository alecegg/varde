from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from messages_backends import AliasResolver, BackendRegistration, backend_registry
from varde_data.backends.files.messages import FilesMessages
from varde_data.records.messages import Delivery, Message, NewMessage
from varde_data.repos.messages import MessageRepository

_backend_params = tuple(
    pytest.param(
        name,
        id=name,
    )
    for name in backend_registry()
)


@pytest.fixture(params=_backend_params)
def message_backend(request: pytest.FixtureRequest) -> BackendRegistration:
    return backend_registry()[request.param]


@pytest.fixture
def messages(message_backend: BackendRegistration, tmp_path: Path) -> MessageRepository:
    return message_backend.factory(tmp_path / "working", AliasResolver())


def _message(message_id: str, to: str = "solo") -> Message:
    return Message("t", "sender", to, "info", message_id, id=message_id)


def test_import_messages_seeds_new_reader(messages: MessageRepository) -> None:
    message = _message("m-00000001")
    assert messages.import_messages((message,)) == (message,)
    assert messages.unread("solo") == (message,)


def test_import_to_unseen_reader_can_be_claimed(messages: MessageRepository) -> None:
    message = _message("m-00000009", "new-reader")
    messages.import_messages((message,))

    assert messages.claim_unread("new-reader", "s", "hook", "t") == (message,)


def test_files_import_respects_existing_cursor_before_seeding(tmp_path: Path) -> None:
    working = tmp_path / "working"
    inbox = working / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    first = _message("m-00000001")
    first_line = (
        b'{"ts":"t","from":"sender","to":"solo","kind":"info",'
        b'"text":"m-00000001","id":"m-00000001"}\n'
    )
    (inbox / "messages.jsonl").write_bytes(first_line)
    (inbox / "cursors").mkdir()
    (inbox / "cursors" / "solo").write_text("0", encoding="ascii")
    repository = FilesMessages(working)
    second = _message("m-00000002")

    repository.import_messages((second,))

    assert repository.peek_unread("solo") == (first, second)


def test_reader_position_uses_message_id_and_preserves_reader_name(
    messages: MessageRepository,
) -> None:
    first = _message("m-00000001", "reader-a")
    second = _message("m-00000002", "reader-a")
    messages.import_messages((first, second))
    messages.import_reader_position("reader-a", first.id)

    assert messages.reader_position("reader-a") == first.id
    assert messages.reader_position("slot-a") is None
    assert messages.unread("reader-a") == (second,)

    messages.import_reader_position("reader-a", None)
    assert messages.reader_position("reader-a") is None
    assert messages.unread("reader-a") == (first, second)


def test_import_deliveries_replays_exact_order_idempotently(
    messages: MessageRepository,
) -> None:
    rows = (
        Delivery("m-00000001", "alias-a", "s1", "hook", "delivered", "t1"),
        Delivery("m-00000001", "alias-a", "s1", "hook", "acked", "t2"),
        Delivery("m-00000002", "reader", "s2", "relay", "legacy", "t3", reason="old"),
        Delivery("m-00000003", "reader", "s3", "relay", "dropped", "t4"),
    )
    messages.import_deliveries(rows)
    messages.import_deliveries(rows)

    assert messages.deliveries() == rows


def test_import_deliveries_empty_reason_and_non_string_detail_are_idempotent(
    messages: MessageRepository,
) -> None:
    row = Delivery(
        "m-00000001",
        "reader",
        "s",
        "hook",
        "legacy",
        "t",
        reason="",
        details=cast("dict[str, str]", {"invalid": 3}),
    )
    messages.import_deliveries((row, row))
    messages.import_deliveries((row,))

    assert len(messages.deliveries()) == 1
    assert messages.deliveries()[0].reason == ""


def test_files_import_deliveries_batches_one_fsync(
    messages: MessageRepository,
    message_backend: BackendRegistration,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if message_backend.name != "files":
        pytest.skip("delivery fsync batching is specific to the files backend")
    import varde_data.backends.files.messages as files_messages

    calls = 0
    real_fsync = files_messages.os.fsync

    def count_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        real_fsync(fd)

    monkeypatch.setattr(files_messages.os, "fsync", count_fsync)
    messages.import_deliveries(
        (
            Delivery("m-00000001", "reader", "s", "hook", "legacy", "t1"),
            Delivery("m-00000002", "reader", "s", "hook", "dropped", "t2"),
        )
    )

    assert calls == 1


def test_import_concluded_union_merges(messages: MessageRepository) -> None:
    messages.mark_concluded("existing")
    messages.import_concluded(("imported", "existing"))
    messages.import_concluded(("later",))

    assert messages.concluded_addresses() == {"existing", "imported", "later"}


def test_status_reports_messages_past_the_reader_watermark(
    messages: MessageRepository,
    message_backend: BackendRegistration,
) -> None:
    if message_backend.name == "memory":
        pytest.skip("below-watermark diagnostics are storage-specific")
    message = messages.append(
        NewMessage("sender", "solo", "info", "below watermark", ts="t")
    )
    assert messages.claim_unread("solo", "s", "hook", "t") == (message,)

    assert messages.status().diagnostics["below_watermark"] == {message.id}


def test_files_import_concluded_does_not_copy_relay_state_into_state_json(
    tmp_path: Path,
) -> None:
    repository = FilesMessages(tmp_path / "working")
    inbox = repository.inbox
    inbox.mkdir(parents=True)
    (inbox / "state.json").write_text(
        '{"concluded_addresses":["state-only"]}', encoding="utf-8"
    )
    relay_state = inbox / "relay" / "state.json"
    relay_state.parent.mkdir(parents=True)
    relay_state.write_text('{"concluded_addresses":["relay-only"]}', encoding="utf-8")

    repository.import_concluded(("imported",))

    state = json.loads((inbox / "state.json").read_text(encoding="utf-8"))
    assert state["concluded_addresses"] == ["imported", "state-only"]
    assert repository.concluded_addresses() == {
        "imported",
        "state-only",
        "relay-only",
    }


def test_append_retries_message_id_collision(
    messages: MessageRepository,
    message_backend: BackendRegistration,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert message_backend.force_next_ids is not None
    message_backend.force_next_ids(messages, ("00000001", "00000002"), monkeypatch)
    messages.import_messages((_message("m-00000001"),))

    if message_backend.name == "files":

        def unexpected_message_ids() -> set[str]:
            raise AssertionError("append parsed the full message-id set")

        monkeypatch.setattr(messages, "message_ids", unexpected_message_ids)

    appended = messages.append(NewMessage("sender", "solo", "info", "new", ts="t"))
    assert appended.id == "m-00000002"
