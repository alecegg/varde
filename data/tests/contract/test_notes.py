from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest
from varde_data.errors import Invalid, NotFound
from varde_data.fixture_domain import FilesNotes, NotesRepository


def _put_worker(root: str, start: int) -> None:
    repository = FilesNotes(Path(root))
    for index in range(20):
        repository.put(f"{start + index}", f"text-{start + index}")


def test_round_trip(notes: NotesRepository) -> None:
    assert notes.put("alpha", "hello") == notes.get("alpha")
    assert notes.list() == ([notes.get("alpha")], [])


def test_not_found(notes: NotesRepository) -> None:
    with pytest.raises(NotFound):
        notes.get("missing")


@pytest.mark.parametrize(("key", "text"), [("", "text"), ("key", " ")])
def test_invalid(notes: NotesRepository, key: str, text: str) -> None:
    with pytest.raises(Invalid):
        notes.put(key, text)


def test_version_changes_after_each_write(notes: NotesRepository) -> None:
    before = notes.version()
    notes.put("key", "one")
    after_first = notes.version()
    notes.put("key", "two")
    after_rewrite = notes.version()
    assert before != after_first
    assert after_first != after_rewrite


def test_list_skips_and_reports_corrupt_entry(tmp_path: Path) -> None:
    notes = FilesNotes(tmp_path)
    notes.put("valid", "text")
    (notes.root / "corrupt.json").write_text("{broken", encoding="utf-8")
    records, skipped = notes.list()
    assert [record.key for record in records] == ["valid"]
    assert skipped == ["corrupt.json"]


def test_concurrent_writers(shared_notes: NotesRepository, tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    workers = [
        context.Process(target=_put_worker, args=(str(tmp_path), start))
        for start in (0, 20)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(15)
        assert worker.exitcode == 0
    records, skipped = shared_notes.list()
    assert skipped == []
    assert len(records) == 40
