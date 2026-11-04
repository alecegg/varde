from __future__ import annotations

from pathlib import Path

from varde_data.backends.files.friction import FilesFriction
from varde_data.repos.friction import FrictionAddRequest


def test_reads_folded_log_without_rewriting_it(tmp_path: Path) -> None:
    store = FilesFriction(tmp_path)
    store.add(FrictionAddRequest("One", "test", "evidence", "/work", "/repo"))
    log = tmp_path / "friction.jsonl"
    before = log.read_bytes()

    assert store.list_items().total == 1
    assert store.show("one").occurrences.total == 1
    assert log.read_bytes() == before


def test_append_recovers_only_an_unterminated_tail(tmp_path: Path) -> None:
    store = FilesFriction(tmp_path)
    log = tmp_path / "friction.jsonl"
    log.write_bytes(b'{"torn":')

    store.add(FrictionAddRequest("One", "test", "evidence", "/work", "/repo"))

    assert log.read_bytes().startswith(b'{"torn":') is False
    assert log.read_bytes().endswith(b"\n")
    assert store.list_items().total == 1
