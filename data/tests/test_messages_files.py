from __future__ import annotations

import json
import multiprocessing
import time
from pathlib import Path

import pytest
from varde_data.backends.files.messages import FilesMessages
from varde_data.errors import Locked
from varde_data.locking import file_lock
from varde_data.messages import open_messages
from varde_data.records.messages import Delivery, Message, NewMessage
from varde_data.store_mode import _mark_import_verified


def _claim(working: str, output: multiprocessing.Queue[int]) -> None:
    repository = FilesMessages(Path(working))
    output.put(len(repository.claim_unread("reader", "session", "hook", "t")))


def _import_message(working: str, output: multiprocessing.Queue[int]) -> None:
    row = Message("t", "sender", "reader", "info", "import", id="m-12345678")
    output.put(len(FilesMessages(Path(working)).import_messages((row,))))


def test_append_prefixes_torn_tail_without_discarding_it(tmp_path: Path) -> None:
    repository = FilesMessages(tmp_path)
    first = repository.append(NewMessage("sender", "reader", "info", "first", ts="t"))
    path = tmp_path / ".cache/inbox/messages.jsonl"
    with path.open("ab") as stream:
        stream.write(b"{torn")
    second = repository.append(NewMessage("sender", "reader", "info", "second", ts="t"))
    assert path.read_bytes().endswith(
        b"{torn\n"
        + (
            f'{{"ts":"t","from":"sender","to":"reader","kind":"info","text":"second","id":"{second.id}"}}\n'
        ).encode()
    )
    assert [item.id for item in repository.read_all().records] == [first.id, second.id]


def test_delivery_reads_cache_history_and_parse_only_appended_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import varde_data.backends.files.messages as messages_files

    repository = FilesMessages(tmp_path)
    first = Delivery("m-00000001", "reader", "s", "hook", "acked", "t")
    second = Delivery("m-00000002", "reader", "s", "hook", "acked", "t")
    repository._append_delivery(first)
    assert repository.deliveries() == (first,)

    def fail_full_read(*_args, **_kwargs):
        raise AssertionError("delivery history was read from the beginning")

    monkeypatch.setattr(messages_files, "read_complete_lines", fail_full_read)
    assert repository.deliveries() == (first,)

    repository._append_delivery(second)
    assert repository.deliveries() == (first, second)


def test_read_all_parses_only_new_complete_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import varde_data.backends.files.messages as messages_files

    repository = FilesMessages(tmp_path)
    repository.append(NewMessage("sender", "reader", "info", "first", ts="t"))
    path = tmp_path / ".cache" / "inbox" / "messages.jsonl"
    assert len(repository.read_all().records) == 1

    parsed_lengths = []
    parse = messages_files.parse_messages

    def counted_parse(data: bytes, *, start_offset: int = 0, start_line: int = 0):
        parsed_lengths.append((len(data), start_offset, start_line))
        return parse(data, start_offset=start_offset, start_line=start_line)

    monkeypatch.setattr(messages_files, "parse_messages", counted_parse)
    repository.append(NewMessage("sender", "reader", "info", "second", ts="t"))

    assert len(repository.read_all().records) == 2
    assert len(parsed_lengths) == 1
    assert parsed_lengths[0][0] < path.stat().st_size
    assert parsed_lengths[0][1] > 0
    assert parsed_lengths[0][2] == 1


def test_message_cache_resets_after_truncate_and_regrow(tmp_path: Path) -> None:
    repository = FilesMessages(tmp_path)
    old = repository.append(NewMessage("sender", "reader", "info", "old", ts="t"))
    path = tmp_path / ".cache" / "inbox" / "messages.jsonl"
    assert [row.id for row in repository.read_all().records] == [old.id]

    replacements = [
        NewMessage("sender", "reader", "info", text, ts="t")
        for text in ("replacement one", "replacement two")
    ]
    with path.open("wb") as stream:
        for row in replacements:
            stream.write(
                (
                    json.dumps(
                        {
                            "ts": row.ts,
                            "from": row.from_,
                            "to": row.to,
                            "kind": row.kind,
                            "text": row.text,
                        }
                    )
                    + "\n"
                ).encode()
            )

    actual = repository.read_all().records
    assert [row.text for row in actual] == ["replacement one", "replacement two"]


def test_delivery_cache_resets_after_truncate_and_regrow(tmp_path: Path) -> None:
    repository = FilesMessages(tmp_path)
    path = tmp_path / ".cache" / "inbox" / "deliveries.jsonl"
    old = Delivery("m-00000001", "reader", "s", "hook", "acked", "t")
    repository._append_delivery(old)
    assert repository.deliveries() == (old,)

    replacements = [
        Delivery(f"m-0000000{number}", "reader", "s", "hook", "acked", "t")
        for number in (2, 3)
    ]
    path.write_bytes(
        b"".join(
            (
                json.dumps(
                    {
                        "message_id": row.message_id,
                        "reader": row.reader,
                        "session": row.session,
                        "via": row.via,
                        "event": row.event,
                        "at": row.at,
                    }
                )
                + "\n"
            ).encode()
            for row in replacements
        )
    )
    assert repository.deliveries() == tuple(replacements)


def test_claim_waits_for_reader_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    import varde_data.backends.files.messages as files_messages

    actual_lock = files_messages.file_lock

    @contextmanager
    def short_lock(path: Path, *, timeout: float):
        with actual_lock(path, timeout=0.05):
            yield

    monkeypatch.setattr(files_messages, "file_lock", short_lock)
    repository = FilesMessages(tmp_path)
    repository.append(NewMessage("sender", "reader", "info", "hello", ts="t"))
    with (
        file_lock(tmp_path / ".cache/inbox/.reader.lock", timeout=1),
        pytest.raises(Locked),
    ):
        repository.claim_unread("reader", "session", "hook", "t")


def test_factory_files_hook_claim_uses_busy_timeout(tmp_path: Path) -> None:
    _mark_import_verified(tmp_path, verified_at="2026-10-24T00:00:00Z")
    repository = open_messages(tmp_path, "files", busy_timeout=0.04)
    repository.append(NewMessage("sender", "reader", "info", "hello", ts="t"))
    started = time.monotonic()
    with (
        file_lock(tmp_path / ".cache/inbox/.reader.lock", timeout=1),
        pytest.raises(Locked),
    ):
        repository.claim_unread("reader", "session", "hook", "t")
    assert time.monotonic() - started < 0.2


def test_from_start_reader_advances_past_historically_delivered_messages(
    tmp_path: Path,
) -> None:
    repository = FilesMessages(tmp_path)
    messages = tuple(
        Message("t", "sender", "reader", "info", str(index), id=f"m-{index:08}")
        for index in range(3)
    )
    repository.import_messages(messages)
    repository.import_deliveries(
        tuple(
            Delivery(message.id or "", "reader", "old", "hook", "delivered", "t")
            for message in messages[:2]
        )
    )

    repository.register_reader("reader", from_start=True)

    lines = repository._messages.read_bytes().splitlines(keepends=True)
    assert repository._watermark("reader") == sum(map(len, lines[:2]))
    assert [message.id for message in repository.peek_unread("reader")] == [
        messages[2].id
    ]


def test_multi_process_claim_delivers_message_once(tmp_path: Path) -> None:
    repository = FilesMessages(tmp_path)
    repository.append(NewMessage("sender", "reader", "info", "hello", ts="t"))
    context = multiprocessing.get_context("spawn")
    output: multiprocessing.Queue[int] = context.Queue()
    workers = [
        context.Process(target=_claim, args=(str(tmp_path), output)) for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(30)
        assert worker.exitcode == 0
    assert sorted(output.get(timeout=2) for _ in workers) == [0, 1]


def test_claim_does_not_advance_past_append_after_peek(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from varde_data.locking import append_line

    repository = FilesMessages(tmp_path)
    first = repository.append(NewMessage("sender", "reader", "info", "first", ts="t"))
    peek = repository._peek_snapshot
    appended = False

    def append_between_peek_and_advance(
        reader: str, start: int = 0, resolver=None, delivered_ids=None
    ):
        nonlocal appended
        result = peek(reader, start, resolver, delivered_ids)
        if not appended:
            row = {
                "ts": "t",
                "from": "sender",
                "to": "reader",
                "kind": "info",
                "text": "raced",
                "id": "m-87654321",
            }
            append_line(
                tmp_path / ".cache/inbox/messages.jsonl",
                json.dumps(row, separators=(",", ":")).encode(),
                lock_path=tmp_path / ".cache/inbox/.messages.lock",
            )
            appended = True
        return result

    monkeypatch.setattr(repository, "_peek_snapshot", append_between_peek_and_advance)
    assert repository.claim_unread("reader", "session", "hook", "t") == (first,)
    assert [
        message.text for message in repository.claim_unread("reader", "s2", "hook", "t")
    ] == ["raced"]


def test_watermark_uses_lf_readline_with_lone_cr(tmp_path: Path) -> None:
    from varde_data.records.messages import Delivery, Message

    repository = FilesMessages(tmp_path)
    first = Message("t", "sender", "reader", "info", "cr", id="m-11111111")
    second = Message("t", "sender", "reader", "info", "later", id="m-22222222")
    repository.register_reader("reader", from_start=True)
    repository.import_messages((first, second))
    path = tmp_path / ".cache/inbox/messages.jsonl"
    raw = path.read_bytes().replace(b'{"ts"', b'{\r"ts"', 1)
    path.write_bytes(raw)
    assert (
        repository.record_delivery(
            Delivery(second.id or "", "reader", "s", "cli", "delivered", "t")
        ).value
        == "recorded"
    )
    assert repository.unread("reader") == (first,)


def test_crash_after_delivery_append_recovers_from_log(
    tmp_path: Path, monkeypatch
) -> None:
    repository = FilesMessages(tmp_path)
    sent = repository.append(NewMessage("sender", "reader", "info", "hello", ts="t"))

    def crash(_: str, *, limit: int | None = None, resolver=None) -> None:
        raise RuntimeError("simulated crash after durable event append")

    monkeypatch.setattr(repository, "_advance_watermark", crash)
    try:
        repository.record_delivery(
            Delivery(sent.id or "", "reader", "s", "cli", "delivered", "t")
        )
    except RuntimeError as error:
        assert "simulated crash" in str(error)
    else:
        raise AssertionError("crash hook should interrupt index update")
    recovered = FilesMessages(tmp_path)
    assert recovered.unread("reader") == ()
    assert (
        tmp_path / ".cache/inbox/index/reader.json"
    ).read_bytes() == b'{"watermark": 0}'


def test_files_version_excludes_address_and_relay_state(tmp_path: Path) -> None:
    repository = FilesMessages(tmp_path)
    slots = tmp_path / ".cache/inbox/slots"
    slots.mkdir(parents=True)
    slot = slots / "s1.json"
    slot.write_text('{"slot":"s1","aliases":[]}', encoding="utf-8")
    before_alias = repository.version()
    slot.write_text('{"slot":"s1","aliases":["p2"]}', encoding="utf-8")
    assert repository.version() == before_alias

    before_relay = repository.version()
    relay_state = tmp_path / ".cache/inbox/relay/state.json"
    relay_state.parent.mkdir(parents=True)
    relay_state.write_text('{"concluded_addresses":[]}', encoding="utf-8")
    after_relay = repository.version()
    assert after_relay == before_relay
    relay_state.write_text('{"concluded_addresses":["done"]}', encoding="utf-8")
    assert repository.version() == after_relay
    assert repository.concluded_addresses() == {"done"}


def test_legacy_bytes_empty_claim_and_repeated_ack(tmp_path: Path) -> None:
    from varde_data.records.messages import Delivery

    repository = FilesMessages(tmp_path)
    repository.append(NewMessage("sender", "someone-else", "info", "other", ts="t"))
    assert repository.claim_unread("reader", "s", "hook", "t") == ()
    assert (tmp_path / ".cache/inbox/cursors/reader").read_text() == str(
        len((tmp_path / ".cache/inbox/messages.jsonl").read_bytes())
    )
    index = tmp_path / ".cache/inbox/index/reader.json"
    assert not index.read_bytes().endswith(b"\n")
    delivered_cache = json.loads(
        (tmp_path / ".cache/inbox/index/reader.delivered.json").read_bytes()
    )
    assert delivered_cache["ids"] == []

    sent = repository.append(NewMessage("sender", "reader", "info", "mail", ts="t"))
    repository.record_delivery(
        Delivery(sent.id or "", "reader", "s", "cli", "delivered", "t")
    )
    delivered_cache = json.loads(
        (tmp_path / ".cache/inbox/index/reader.delivered.json").read_bytes()
    )
    assert delivered_cache["ids"] == [sent.id]
    assert repository.ack("reader", sent.id or "", now="t")
    assert repository.ack("reader", sent.id or "", now="t")
    acked = [event for event in repository.deliveries() if event.event == "acked"]
    assert len(acked) == 2

    repository.mark_concluded("done")
    assert (
        tmp_path / ".cache/inbox/state.json"
    ).read_bytes() == b'{"concluded_addresses":["done"]}'


def test_delivery_after_drop_is_skipped(tmp_path: Path) -> None:
    repository = FilesMessages(tmp_path)
    sent = repository.append(NewMessage("sender", "reader", "info", "mail", ts="t"))
    dropped = Delivery(sent.id or "", "reader", "s", "relay", "dropped", "t")
    delivered = Delivery(sent.id or "", "reader", "s", "cli", "delivered", "t2")
    assert repository.record_delivery(dropped).value == "recorded"
    before = repository.deliveries()
    assert repository.record_delivery(delivered).value == "skipped"
    assert repository.deliveries() == before


def test_concurrent_imports_dedupe_under_messages_lock(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    output: multiprocessing.Queue[int] = context.Queue()
    workers = [
        context.Process(target=_import_message, args=(str(tmp_path), output))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(30)
        assert worker.exitcode == 0
    assert sorted(output.get(timeout=2) for _ in workers) == [0, 1]
    assert [message.id for message in FilesMessages(tmp_path).read_all().records] == [
        "m-12345678"
    ]


def test_read_methods_do_not_take_reader_or_message_locks(tmp_path: Path) -> None:
    repository = FilesMessages(tmp_path)
    repository.append(NewMessage("sender", "reader", "info", "hello", ts="t"))
    with (
        file_lock(tmp_path / ".cache/inbox/.reader.lock", timeout=1),
        file_lock(tmp_path / ".cache/inbox/.messages.lock", timeout=1),
    ):
        assert repository.read_all().records
        repository.read_since(repository.head())
        repository.peek_unread("reader")
        repository.pending_by_address()
        repository.deliveries()
        repository.status()
        repository.version()
        repository.concluded_addresses()


def test_version_tracks_derived_directory_replacements_without_globbing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = FilesMessages(tmp_path)
    inbox = tmp_path / ".cache" / "inbox"
    index = inbox / "index" / "reader.json"
    cursor = inbox / "cursors" / "reader.json"
    index.parent.mkdir(parents=True)
    cursor.parent.mkdir(parents=True)
    index.write_text("old", encoding="utf-8")
    cursor.write_text("old", encoding="utf-8")
    before = repository.version()

    def fail_glob(*_args, **_kwargs):
        raise AssertionError("version enumerated derived files")

    monkeypatch.setattr(Path, "glob", fail_glob)
    replacement = index.with_suffix(".tmp")
    replacement.write_text("new", encoding="utf-8")
    replacement.replace(index)

    assert repository.version() != before


def _message_line(text: str, ident: str) -> bytes:
    row = {
        "ts": "t",
        "from": "s",
        "to": "reader",
        "kind": "info",
        "text": text,
        "id": ident,
    }
    return (json.dumps(row) + "\n").encode()


def test_message_cache_survives_prefix_preserving_rewrite(tmp_path: Path) -> None:
    repository = FilesMessages(tmp_path)
    path = tmp_path / ".cache" / "inbox" / "messages.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    old = [_message_line(f"old {n}", f"m-{n:08d}") for n in range(12)]
    path.write_bytes(b"".join(old))
    assert len(repository.read_all().records) == 12

    new = old[:4] + [_message_line(f"new {n}", f"m-9{n:07d}") for n in range(16)]
    with path.open("r+b") as stream:  # same inode, prefix kept, regrown past old size
        stream.truncate(0)
        stream.write(b"".join(new))

    records = repository.read_all().records
    assert [row.id for row in records] == [f"m-{n:08d}" for n in range(4)] + [
        f"m-9{n:07d}" for n in range(16)
    ]


def _delivery_line(message_id: str) -> bytes:
    row = {
        "message_id": message_id,
        "reader": "reader",
        "session": "s",
        "via": "hook",
        "event": "acked",
        "at": "t",
    }
    return (json.dumps(row) + "\n").encode()


def test_delivery_cache_survives_prefix_preserving_rewrite(tmp_path: Path) -> None:
    repository = FilesMessages(tmp_path)
    path = tmp_path / ".cache" / "inbox" / "deliveries.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    old = [_delivery_line(f"m-{n:08d}") for n in range(12)]
    path.write_bytes(b"".join(old))
    assert len(repository.deliveries()) == 12

    new = old[:4] + [_delivery_line(f"m-9{n:07d}") for n in range(16)]
    with path.open("r+b") as stream:
        stream.truncate(0)
        stream.write(b"".join(new))

    ids = [row.message_id for row in repository.deliveries()]
    assert ids == [f"m-{n:08d}" for n in range(4)] + [f"m-9{n:07d}" for n in range(16)]
