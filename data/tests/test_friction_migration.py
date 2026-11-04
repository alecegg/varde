from __future__ import annotations

import json
import multiprocessing
import shutil
import sqlite3
from pathlib import Path

import pytest
from varde_data.backends.sqlite.friction import SqliteFrictionIndex
from varde_data.errors import Invalid
from varde_data.friction_events import fold, replay

FIXTURES = Path(__file__).parent / "fixtures" / "friction"


def _first_touch(root: str, barrier) -> None:
    from varde_data.backends.files.friction import FilesFriction

    barrier.wait(timeout=20)
    FilesFriction(Path(root)).list_items()


@pytest.mark.parametrize("version", (1, 2, 3, 4, 5))
def test_schema_cache_rebuild_preserves_log(tmp_path: Path, version: int) -> None:
    shutil.copy2(FIXTURES / f"schema-v{version}" / "learn.db", tmp_path / "learn.db")
    shutil.copy2(FIXTURES / "friction.jsonl", tmp_path / "friction.jsonl")
    before = (tmp_path / "friction.jsonl").read_bytes()

    SqliteFrictionIndex(tmp_path).refresh()

    after = (tmp_path / "friction.jsonl").read_bytes()
    complete_prefix = before[: before.rfind(b"\n") + 1]
    if version < 4:
        assert after.startswith(complete_prefix)
        assert after != before
    else:
        assert after == before
    with sqlite3.connect(tmp_path / "learn.db") as db:
        assert (
            db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[
                0
            ]
            == "5"
        )
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM items").fetchone()[0] == len(
            fold(replay(tmp_path / "friction.jsonl").events).items
        )


def test_legacy_database_is_backed_up_and_imported(tmp_path: Path) -> None:
    shutil.copy2(FIXTURES / "legacy-no-log" / "learn.db", tmp_path / "learn.db")
    legacy_counts = _counts(tmp_path / "learn.db")

    SqliteFrictionIndex(tmp_path).refresh()

    log_counts = _fold_counts(tmp_path / "friction.jsonl")
    assert legacy_counts == log_counts
    assert (tmp_path / "learn.db.pre-log").is_file()


def test_legacy_migration_preserves_zero_and_null_provenance(
    tmp_path: Path,
) -> None:
    shutil.copy2(FIXTURES / "schema-v5" / "learn.db", tmp_path / "learn.db")

    SqliteFrictionIndex(tmp_path).refresh()

    with sqlite3.connect(tmp_path / "learn.db") as db:
        provenance = db.execute(
            "SELECT witness_id,record_index,byte_start,byte_end "
            "FROM incident_provenance"
        ).fetchone()
    assert provenance == (None, 0, 0, 1)


def test_reads_use_migrated_ids_and_slugs(tmp_path: Path) -> None:
    from varde_data.backends.files.friction import FilesFriction

    shutil.copy2(FIXTURES / "legacy-no-log" / "learn.db", tmp_path / "learn.db")
    store = FilesFriction(tmp_path)
    page = store.list_items()

    with sqlite3.connect(tmp_path / "learn.db") as db:
        rows = db.execute("SELECT id,slug,title FROM items ORDER BY id").fetchall()
    assert len(page.items) == len(rows)
    for row_id, slug, title in rows:
        by_slug = store.show(slug).item
        by_id = store.show(str(row_id)).item
        assert (by_slug.title, by_id.title) == (title, title)
        assert (by_slug.event_id, by_slug.slug) == (by_id.event_id, slug)


def test_concurrent_first_touch_migrates_once(tmp_path: Path) -> None:
    shutil.copy2(FIXTURES / "legacy-no-log" / "learn.db", tmp_path / "learn.db")
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(4)
    workers = [
        context.Process(target=_first_touch, args=(str(tmp_path), barrier))
        for _ in range(4)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)
        assert not worker.is_alive(), "first-touch worker did not finish"
        assert worker.exitcode == 0

    lines = (tmp_path / "friction.jsonl").read_text().splitlines()
    event_ids = [json.loads(line)["id"] for line in lines]
    assert len(fold(replay(tmp_path / "friction.jsonl").events).items) == 1
    assert len(event_ids) == len(set(event_ids))


def test_interrupted_migration_preserves_log_and_rows(tmp_path: Path) -> None:
    shutil.copytree(FIXTURES / "interrupted-migration", tmp_path, dirs_exist_ok=True)
    before = (tmp_path / "friction.jsonl").read_bytes()
    expected = _fold_counts(tmp_path / "friction.jsonl")

    SqliteFrictionIndex(tmp_path).refresh()

    assert (tmp_path / "friction.jsonl").read_bytes() == before
    assert _counts(tmp_path / "learn.db") == expected


def test_newer_database_version_is_invalid(tmp_path: Path) -> None:
    SqliteFrictionIndex(tmp_path).refresh()
    with sqlite3.connect(tmp_path / "learn.db") as db:
        db.execute("UPDATE meta SET value='6' WHERE key='schema_version'")
    with pytest.raises(Invalid, match="newer"):
        SqliteFrictionIndex(tmp_path).refresh()


def test_read_rebuilds_corrupt_derived_database_from_log(tmp_path: Path) -> None:
    from varde_data.backends.files.friction import FilesFriction
    from varde_data.repos.friction import FrictionAddRequest

    store = FilesFriction(tmp_path)
    store.add(FrictionAddRequest("One", "test", "evidence", "/work"))
    database = tmp_path / "learn.db"
    database.write_bytes(b"corrupt derived cache")

    page = store.list_items()

    assert page.total == 1
    assert database.read_bytes() != b"corrupt derived cache"
    assert (tmp_path / "learn.db.corrupt").read_bytes() == b"corrupt derived cache"


def test_fresh_schema_keeps_checks_and_delete_cascades(tmp_path: Path) -> None:
    SqliteFrictionIndex(tmp_path).refresh()
    with sqlite3.connect(tmp_path / "learn.db") as db:
        db.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            db.execute(
                "INSERT INTO items VALUES(1,'bad','Bad','test',NULL,'unknown',NULL,"
                "'2026-01-01T00:00:00.000Z')"
            )
        db.execute(
            "INSERT INTO items VALUES(1,'valid','Valid','test',NULL,'open',NULL,"
            "'2026-01-01T00:00:00.000Z')"
        )
        db.execute(
            "INSERT INTO occurrences VALUES(1,1,'2026-01-01T00:00:00.000Z','/work',"
            "NULL,NULL,'evidence',NULL)"
        )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            db.execute(
                "INSERT INTO incident_provenance VALUES('key',1,2,'harness','thread',"
                "'kind',NULL,'source',0,0,0,'record','payload')"
            )
        db.execute("DELETE FROM items WHERE id=1")
        assert db.execute("SELECT count(*) FROM occurrences").fetchone()[0] == 0


def _counts(database: Path) -> tuple[int, int, int, int]:
    with sqlite3.connect(database) as db:
        return tuple(
            db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608 - table names are a fixed test tuple.
            for table in ("items", "occurrences", "status_changes", "adoptions")
        )


def _fold_counts(log: Path) -> tuple[int, int, int, int]:
    state = fold(replay(log).events)
    return (
        len(state.items),
        len(state.occurrences),
        len(state.status_changes),
        len(state.adoptions),
    )
