from __future__ import annotations

from pathlib import Path

from varde_toz.chunk import Chunk
from varde_toz.project import project_root
from varde_toz.store import NewCapture, Store


def test_current_schema_open_does_not_recreate_init_lock(tmp_path: Path) -> None:
    path = tmp_path / "toz.db"
    with Store(path):
        pass
    lock_path = path.with_suffix(".db.init.lock")
    lock_path.unlink()
    with Store(path):
        pass
    assert not lock_path.exists()


def test_insert_capture_batches_chunks_and_indexes_them(tmp_path: Path) -> None:
    path = tmp_path / "toz.db"
    chunks = [
        (
            "stdout",
            Chunk(index, f"row {index}", index + 1, index + 1, "text", f"body {index}"),
        )
        for index in range(3)
    ]
    with Store(path) as store:
        handle = store.insert_capture(NewCapture("test", "capture", "test"), chunks)
        row = store.get_by_handle(handle)
        assert row["chunk_count"] == 3
        assert [item["body"] for item in store.chunks_for(row["id"])] == [
            "body 0",
            "body 1",
            "body 2",
        ]
        assert store.search("body", limit=10)


def test_project_root_walks_to_git_marker_without_subprocess(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    nested = root / "one" / "two"
    (root / ".git").mkdir(parents=True)
    nested.mkdir(parents=True)

    assert project_root(nested) == root
    outside = tmp_path / "outside"
    outside.mkdir()
    assert project_root(outside) == outside
