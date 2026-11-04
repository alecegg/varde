"""Learn store marker, writer generation protocol and dispatch."""

import sqlite3
import sys
import time
import types
from contextlib import closing
from pathlib import Path

import pytest
from varde_data.backends.sqlite.learn_schema import (
    SCHEMA_VERSION,
    connect,
    count_rows,
    learn_db_path,
)
from varde_data.calls import open_calls
from varde_data.errors import Invalid, Locked
from varde_data.friction import open_friction
from varde_data.learn_store_mode import (
    DEFAULT_MODE,
    LearnStoreModeInvalid,
    StaleGeneration,
    backend_for,
    exclusive_store_lock,
    flip_domain_locked,
    marker_path,
    read_learn_mode,
    writer_target,
)


def test_absent_marker_means_files_generation_zero(tmp_path: Path) -> None:
    assert read_learn_mode(tmp_path) == DEFAULT_MODE
    assert [backend_for(tmp_path, d) for d in ("friction", "ledger", "calls")] == [
        "files"
    ] * 3


def test_flip_changes_one_domain_and_bumps_generation(tmp_path: Path) -> None:
    record = flip_domain_locked(tmp_path, "calls", "sqlite")
    assert (record.friction, record.ledger, record.calls) == (
        "files",
        "files",
        "sqlite",
    )
    assert record.generation == 1
    assert read_learn_mode(tmp_path) == record
    assert flip_domain_locked(tmp_path, "friction", "sqlite").generation == 2


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        '{"version":2,"friction":"files","ledger":"files","calls":"files","generation":0}',
        '{"version":1,"friction":"mirror","ledger":"files","calls":"files","generation":0}',
        '{"version":1,"friction":"files","ledger":"files","calls":"files","generation":-1}',
    ],
)
def test_damaged_marker_fails_closed(tmp_path: Path, payload: str) -> None:
    marker_path(tmp_path).write_text(payload)
    with pytest.raises(LearnStoreModeInvalid):
        read_learn_mode(tmp_path)


def test_unknown_domain_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(Invalid):
        flip_domain_locked(tmp_path, "plans", "sqlite")


def test_stale_writer_is_refused_after_flip(tmp_path: Path) -> None:
    with writer_target(tmp_path, "calls") as (backend, held):
        assert (backend, held) == ("files", 0)
    flip_domain_locked(tmp_path, "calls", "sqlite")

    with (
        pytest.raises(StaleGeneration),
        writer_target(tmp_path, "calls", held_generation=held),
    ):
        pytest.fail("a stale writer must not reach the old backend")


def test_writer_without_held_generation_follows_the_new_backend(
    tmp_path: Path,
) -> None:
    flip_domain_locked(tmp_path, "calls", "sqlite")
    with writer_target(tmp_path, "calls") as (backend, generation):
        assert (backend, generation) == ("sqlite", 1)
    with writer_target(tmp_path, "friction") as (backend, _):
        assert backend == "files"


def test_exclusive_lock_blocks_writers(tmp_path: Path) -> None:
    with (
        exclusive_store_lock(tmp_path),
        pytest.raises(Locked),
        writer_target(tmp_path, "calls", timeout=0.05),
    ):
        pytest.fail("writer must wait for the flip")


def test_schema_has_expected_tables_and_version(tmp_path: Path) -> None:
    connect(tmp_path).close()
    with closing(sqlite3.connect(learn_db_path(tmp_path))) as db:
        tables = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert {"friction_events", "analyzed", "digests", "cli_calls", "meta"} <= tables
    assert count_rows(tmp_path, "cli_calls") == 0
    with closing(sqlite3.connect(learn_db_path(tmp_path))) as db:
        names = [row[1] for row in db.execute("PRAGMA table_info(cli_calls)")]
        layout = db.execute("SELECT value FROM meta WHERE key = 'calls_layout'")
        assert layout.fetchone() == ("2",)
    assert names == [
        "id",
        "ts",
        "command",
        "status",
        "duration_s",
        "session",
        "guardrail",
        "arg",
    ]


def test_newer_schema_is_rejected(tmp_path: Path) -> None:
    connect(tmp_path).close()
    with closing(sqlite3.connect(learn_db_path(tmp_path))) as db:
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(Invalid):
        connect(tmp_path)


def test_factories_follow_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Fake:
        def __init__(self, root: Path) -> None:
            self.root = root

    for module, attribute in (
        ("varde_data.backends.sqlite.learn_friction", "SqliteLearnFriction"),
        ("varde_data.backends.sqlite.learn_calls", "SqliteCalls"),
    ):
        fake = types.ModuleType(module)
        setattr(fake, attribute, Fake)
        monkeypatch.setitem(sys.modules, module, fake)

    assert type(open_friction(tmp_path)).__name__ == "FilesFriction"
    flip_domain_locked(tmp_path, "friction", "sqlite")
    assert isinstance(open_friction(tmp_path), Fake)
    assert type(open_friction(tmp_path, "files")).__name__ == "FilesFriction"
    flip_domain_locked(tmp_path, "calls", "sqlite")
    assert isinstance(open_calls(tmp_path), Fake)


def _race_flip(root: Path, domain: str, write) -> tuple[int, int, BaseException | None]:
    """Start a files-mode write blocked behind a flip; return rows around it."""
    import threading

    outcome: list[BaseException | None] = []

    def attempt() -> None:
        try:
            write()
            outcome.append(None)
        except BaseException as exc:  # noqa: BLE001
            outcome.append(exc)

    with exclusive_store_lock(root):
        thread = threading.Thread(target=attempt)
        thread.start()
        time.sleep(0.1)
        at_flip = _lines(root)
        flip_domain_locked(root, domain, "sqlite")
    thread.join(10)
    return at_flip, _lines(root), outcome[0]


def _lines(root: Path) -> int:
    return sum(
        len(path.read_text().splitlines())
        for path in root.glob("*.jsonl")
        if path.is_file()
    )


def test_ledger_append_racing_a_flip_is_refused_not_lost(tmp_path: Path) -> None:
    from varde_data.ledger import open_ledger

    ledger = open_ledger(tmp_path, "files")
    ledger.mark("codex", "s1", "2026-01-01", "x")
    before, after, error = _race_flip(
        tmp_path, "ledger", lambda: ledger.mark("codex", "s2", "2026-01-02", "y")
    )
    assert before == after == 1
    assert isinstance(error, StaleGeneration)


def test_friction_append_racing_a_flip_is_refused_not_lost(tmp_path: Path) -> None:
    from varde_data.repos.friction import FrictionAddRequest

    repo = open_friction(tmp_path, "files")
    repo.add(FrictionAddRequest("First", "session", "e", "/work", "/repo"))
    before, after, error = _race_flip(
        tmp_path,
        "friction",
        lambda: repo.add(
            FrictionAddRequest("Second", "session", "e", "/work", "/repo")
        ),
    )
    assert before == after
    assert isinstance(error, StaleGeneration)


def test_files_writer_in_other_domain_is_unaffected_by_flip(tmp_path: Path) -> None:
    from varde_data.ledger import open_ledger

    flip_domain_locked(tmp_path, "calls", "sqlite")
    open_ledger(tmp_path, "files").mark("codex", "s1", "2026-01-01", "x")
    assert _lines(tmp_path) == 1
