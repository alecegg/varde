import os
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any

from varde_learn.memory import searchindex as si
from varde_learn.memory import store
from varde_learn.memory.entry import Entry

KEY = "repo-0123456789abcdef"


def make(entry_id: str, text: str = "body text", **overrides: Any) -> Entry:
    base: dict[str, Any] = {
        "id": entry_id,
        "scope": "global",
        "scope_key": "",
        "text": text,
        "source": "t",
        "created": "c",
    }
    base.update(overrides)
    return Entry(**base)


def seeded(tmp_path: Path) -> tuple[Path, si.Source, Path]:
    root = tmp_path / "mem"
    store.write_entry(root, make("a", "alpha cutover note", title="Alpha", topic="t1"))
    store.write_entry(root, make("b", "beta body", aliases=("bee",), tags=("x",)))
    store.write_entry(root, make("p", "proj", scope="project", scope_key=KEY))
    return root, si.memory_source(root), tmp_path / "data" / "idx.sqlite"


def match(index: Path, term: str) -> list[str]:
    with closing(sqlite3.connect(index)) as conn:
        rows = conn.execute(
            "SELECT e.id FROM entries_fts f JOIN entries e ON e.rowid = f.rowid "
            "WHERE entries_fts MATCH ? ORDER BY bm25(entries_fts)",
            (term,),
        ).fetchall()
    return [r[0] for r in rows]


def test_fts_rebuild_indexes_every_entry(tmp_path) -> None:
    _, source, index = seeded(tmp_path)
    stats = si.rebuild_index(source, index)
    assert (stats.entries, stats.indexed, stats.fts, stats.persisted) == (
        3,
        3,
        True,
        True,
    )
    assert match(index, "cutover") == ["a"]
    assert match(index, "bee") == ["b"]
    assert match(index, "x") == ["b"]
    assert match(index, "t1") == ["a"]
    assert list(index.parent.glob("*.tmp")) == []


def test_fts_missing_still_builds_entries_table(tmp_path, monkeypatch) -> None:
    _, source, index = seeded(tmp_path)
    monkeypatch.setattr(si, "fts5_available", lambda: False)
    stats = si.rebuild_index(source, index)
    assert stats.fts is False
    with closing(sqlite3.connect(index)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 3
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "entries_fts" not in tables
    assert si.refresh_index(source, index).reused == 3


def test_index_stale_refresh_touches_only_changed(tmp_path) -> None:
    root, source, index = seeded(tmp_path)
    si.rebuild_index(source, index)
    assert si.read_entry_rows(source, index) is not None
    assert si.refresh_index(source, index).indexed == 0
    store.write_entry(root, make("a", "alpha rewritten zebra"), overwrite=True)
    store.entry_path(root, "global", "", "b").unlink()
    assert si.read_entry_rows(source, index) is None
    stats = si.refresh_index(source, index)
    assert (stats.indexed, stats.removed, stats.entries) == (1, 1, 2)
    assert match(index, "zebra") == ["a"]
    assert match(index, "cutover") == []
    assert match(index, "bee") == []
    rows = si.read_entry_rows(source, index)
    assert rows is not None
    assert sorted(r["id"] for r in rows) == ["a", "p"]


def test_index_mtime_ns_change_marks_stale(tmp_path) -> None:
    root, source, index = seeded(tmp_path)
    si.rebuild_index(source, index)
    path = store.entry_path(root, "global", "", "a")
    stamp = path.stat()
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1))
    assert path.stat().st_size == stamp.st_size
    assert si.read_entry_rows(source, index) is None
    assert si.refresh_index(source, index).indexed == 1


def test_index_schema_version_mismatch_rebuilds(tmp_path) -> None:
    _, source, index = seeded(tmp_path)
    si.rebuild_index(source, index)
    with closing(sqlite3.connect(index)) as conn, conn:
        conn.execute("UPDATE schema_version SET version = 999")
    assert si.read_entry_rows(source, index) is None
    stats = si.refresh_index(source, index)
    assert stats.indexed == 3
    assert si.read_entry_rows(source, index) is not None


def test_index_reader_never_writes(tmp_path) -> None:
    _, source, index = seeded(tmp_path)
    assert si.read_entry_rows(source, index) is None
    assert not index.exists()
    si.rebuild_index(source, index)
    before = {p.name: p.stat().st_mtime_ns for p in index.parent.iterdir()}
    si.read_entry_rows(source, index)
    assert {p.name: p.stat().st_mtime_ns for p in index.parent.iterdir()} == before


def test_index_corrupt_file_rebuilds(tmp_path) -> None:
    _, source, index = seeded(tmp_path)
    index.parent.mkdir(parents=True)
    index.write_bytes(b"not a database" * 50)
    assert si.read_entry_rows(source, index) is None
    assert si.refresh_index(source, index).indexed == 3


def test_in_memory_index_writes_nothing(tmp_path) -> None:
    _, source, _ = seeded(tmp_path)
    before = {str(p) for p in tmp_path.rglob("*")}
    stats = si.rebuild_index(source, None)
    assert stats.persisted is False
    conn = si.connect(source, None)
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 3
    conn.close()
    assert si.read_entry_rows(source, None) is None
    assert {str(p) for p in tmp_path.rglob("*")} == before


def test_unwritable_index_dir_falls_back_to_memory_with_notice(
    tmp_path, capsys
) -> None:
    _, source, _ = seeded(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory")
    conn = si.connect(source, blocker / "x" / "index.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 3
    conn.close()
    assert "in-memory index" in capsys.readouterr().err


def test_index_rebuilt_when_fts_appears(tmp_path, monkeypatch) -> None:
    _, source, index = seeded(tmp_path)
    with monkeypatch.context() as ctx:
        ctx.setattr(si, "fts5_available", lambda: False)
        si.rebuild_index(source, index)
    stats = si.refresh_index(source, index)
    assert stats.fts is True
    assert stats.indexed == 3


def test_bundle_path_survives_colon_in_bundle_name(tmp_path) -> None:
    bundle = tmp_path / "a:b"
    bundle.mkdir()
    (bundle / "note.md").write_text("---\ndescription: x\n---\nbody\n")
    source = si.bundle_source(bundle, scope_key=KEY)
    entries, _ = source.load()
    assert source.path_of(entries[0]) == bundle / "note.md"


def test_index_file_lives_under_share_dir_not_root(tmp_path) -> None:
    root = tmp_path / "mem"
    data = tmp_path / "data"
    path = si.index_file_for(root, data)
    assert path.parent == data / "varde" / "memory-index"
    assert not path.is_relative_to(root)


def test_index_concurrent_rebuilds_leave_a_valid_index(tmp_path) -> None:
    _, source, index = seeded(tmp_path)
    errors: list[BaseException] = []

    def work() -> None:
        try:
            for _ in range(5):
                si.rebuild_index(source, index)
        except BaseException as error:  # noqa: BLE001 - collected and asserted
            errors.append(error)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    rows = si.read_entry_rows(source, index)
    assert rows is not None
    assert len(rows) == 3
    assert list(index.parent.glob("*.tmp")) == []


def test_index_bundle_source_flat_and_nested(tmp_path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "notes").mkdir(parents=True)
    (bundle / "top.md").write_text("---\ndescription: Top\n---\nzulu body\n")
    (bundle / "notes" / "deep.md").write_text("# Deep\nyankee\n")
    source = si.bundle_source(bundle, scope_key=KEY)
    index = tmp_path / "idx.sqlite"
    stats = si.rebuild_index(source, index)
    assert stats.entries == 2
    assert match(index, "yankee") == ["notes-deep"]
    assert si.read_entry_rows(source, index) is not None
