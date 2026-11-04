"""CallsRepository contract across memory, files and sqlite, plus the handlers."""

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from varde_data.backends.files.calls import CALLS_NAME
from varde_data.calls import open_calls
from varde_data.errors import LearnStoreIo, Locked
from varde_data.learn_handlers import calls as handlers
from varde_data.learn_store_mode import (
    StaleGeneration,
    exclusive_store_lock,
    flip_domain_locked,
)
from varde_data.repos.calls import CallsRepository

Factory = Callable[[Path], CallsRepository]


def _sqlite(root: Path) -> CallsRepository:
    flip_domain_locked(root, "calls", "sqlite")
    return open_calls(root)


FACTORIES: dict[str, Factory] = {
    "memory": lambda root: open_calls(root, "memory"),
    "files": open_calls,
    "sqlite": _sqlite,
}


@pytest.fixture(params=tuple(FACTORIES))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> CallsRepository:
    return FACTORIES[request.param](tmp_path)


def call(index: int, **extra: object) -> dict[str, object]:
    return {
        "ts": f"2026-10-22T10:00:{index:02d}Z",
        "command": f"cmd {index}",
        "status": "success",
        "duration_s": 0.5,
        "session": "s1",
        **extra,
    }


def test_append_then_read_preserves_order_and_values(store: CallsRepository) -> None:
    rows = [call(2), call(1, guardrail="g"), call(3, session=None)]
    for row in rows:
        store.append(row)
    assert store.read() == rows
    assert store.read_strict() == rows


def test_read_strict_since_filters_by_parsed_timestamp(store: CallsRepository) -> None:
    stamps = [
        "2026-10-20T23:59:59Z",
        "2026-10-21T00:00:00Z",
        "2026-10-21T02:00:00+02:00",  # 00:00 UTC, equal to the cutoff
        "2026-10-21T01:30:00+02:00",  # 23:30 UTC the day before: older
        "2026-10-20T20:00:00-05:00",  # 01:00 UTC on the 21st: newer
        "2026-10-22T00:00:00.5+00:00",
    ]
    rows = [
        {**call(0), "ts": stamp, "command": f"c{n}"} for n, stamp in enumerate(stamps)
    ]
    for row in rows:
        store.append(row)
    since = datetime(2026, 10, 21, tzinfo=UTC)
    assert [r["command"] for r in store.read_strict(since)] == ["c1", "c2", "c4", "c5"]
    assert store.read_strict(None) == rows
    assert store.read_strict(datetime(2027, 1, 1, tzinfo=UTC)) == []


def test_read_empty_store(store: CallsRepository) -> None:
    assert store.read() == []
    assert store.read_strict() == []


def test_concurrent_appends_keep_every_row(store: CallsRepository) -> None:
    rows = [call(index) for index in range(20)]
    threads = [threading.Thread(target=store.append, args=(row,)) for row in rows]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(str(row["ts"]) for row in store.read()) == sorted(
        str(row["ts"]) for row in rows
    )


def test_files_backend_format_mode_and_newline_repair(tmp_path: Path) -> None:
    path = tmp_path / CALLS_NAME
    path.write_text('{"old":true}', encoding="utf-8")
    path.chmod(0o644)
    open_calls(tmp_path).append(call(1))
    assert path.stat().st_mode & 0o777 == 0o600
    lines = path.read_text().splitlines()
    assert lines[0] == '{"old":true}'
    assert json.loads(lines[1]) == call(1)


def test_files_read_skips_malformed_lines_and_strict_raises_on_io(
    tmp_path: Path,
) -> None:
    (tmp_path / CALLS_NAME).write_text('nope\n[1]\n{"ts":"t","command":"c"}\n{"x"')
    store = open_calls(tmp_path)
    assert store.read() == [{"ts": "t", "command": "c"}]
    bad = tmp_path / "bad"
    (bad / CALLS_NAME).mkdir(parents=True)
    assert open_calls(bad).read() == []
    with pytest.raises(LearnStoreIo) as raised:
        open_calls(bad).read_strict()
    assert raised.value.operation == "read CLI calls"


def test_files_writer_is_refused_after_flip(tmp_path: Path) -> None:
    store = open_calls(tmp_path)
    store.append(call(1))
    flip_domain_locked(tmp_path, "calls", "sqlite")
    with pytest.raises(StaleGeneration):
        store.append(call(2))
    assert len((tmp_path / CALLS_NAME).read_text().splitlines()) == 1


def test_sqlite_writer_with_old_generation_is_refused(tmp_path: Path) -> None:
    flip_domain_locked(tmp_path, "calls", "sqlite")
    store = open_calls(tmp_path)
    store.append(call(1))
    flip_domain_locked(tmp_path, "friction", "sqlite")
    with pytest.raises(StaleGeneration):
        store.append(call(2))
    assert open_calls(tmp_path).read() == [call(1)]


def test_sqlite_append_is_refused_while_a_flip_holds_the_lock(tmp_path: Path) -> None:
    store = _sqlite(tmp_path)
    with exclusive_store_lock(tmp_path), pytest.raises(Locked):
        store.append(call(1))


def test_unknown_backend(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown calls backend"):
        open_calls(tmp_path, "nope")


def _write_file(root: Path, rows: list[dict[str, object]]) -> None:
    text = "".join(json.dumps(row) + "\n" for row in rows)
    (root / CALLS_NAME).write_text(text + "garbage\n")


def test_handlers_migrate_verify_and_retire(tmp_path: Path) -> None:
    rows = [call(index) for index in range(25)]
    _write_file(tmp_path, rows)
    assert handlers.rows(tmp_path) == 25
    assert handlers.migrate(tmp_path, dry_run=True) == {
        "ok": True,
        "rows": 25,
        "skipped_lines": 1,
    }
    assert not (tmp_path / "learn.sqlite3").exists()
    result = handlers.migrate(tmp_path, dry_run=False)
    assert result["ok"] is True
    assert result["sqlite_rows"] == 25
    assert Path(result["backup"]).is_file()
    assert handlers.migrate(tmp_path, dry_run=False)["sqlite_rows"] == 25
    flip_domain_locked(tmp_path, "calls", "sqlite")
    sqlite = open_calls(tmp_path)
    assert sqlite.read() == rows
    sqlite.append(call(30))
    assert handlers.verify(tmp_path)["ok"] is True
    assert handlers.rows(tmp_path) == 26
    removed = handlers.retire(tmp_path)["removed"]
    assert CALLS_NAME in removed
    assert not (tmp_path / CALLS_NAME).exists()


def test_verify_detects_count_and_content_mismatch(tmp_path: Path) -> None:
    _write_file(tmp_path, [call(1), call(2)])
    handlers.migrate(tmp_path, dry_run=False)
    _write_file(tmp_path, [call(1), call(2), call(3)])
    assert handlers.verify(tmp_path)["ok"] is False
    _write_file(tmp_path, [call(1), call(9)])
    verdict = handlers.verify(tmp_path)
    assert (verdict["ok"], verdict["mismatch_at"]) == (False, 1)


def _migrate_and_flip(root: Path) -> None:
    handlers.migrate(root, dry_run=False)
    flip_domain_locked(root, "calls", "sqlite")


def test_migrate_after_flip_keeps_post_flip_rows(tmp_path: Path) -> None:
    _write_file(tmp_path, [call(1)])
    _migrate_and_flip(tmp_path)
    open_calls(tmp_path).append(call(2))
    result = handlers.migrate(tmp_path, dry_run=False)
    assert result["already_migrated"] is True
    assert [row["command"] for row in open_calls(tmp_path).read()] == ["cmd 1", "cmd 2"]


def test_retire_refuses_in_files_mode_and_when_verify_fails(tmp_path: Path) -> None:
    _write_file(tmp_path, [call(1), call(2)])
    with pytest.raises(ValueError, match="not on sqlite"):
        handlers.retire(tmp_path)
    _migrate_and_flip(tmp_path)
    _write_file(tmp_path, [call(1), call(9)])
    with pytest.raises(ValueError, match="verify failed"):
        handlers.retire(tmp_path)
    assert (tmp_path / CALLS_NAME).exists()


def test_migrate_skips_non_importable_lines_and_retire_saves_them(
    tmp_path: Path,
) -> None:
    lines = [json.dumps(call(1)), "garbage", '{"command":"no ts"}', "", '{"torn"']
    (tmp_path / CALLS_NAME).write_text("\n".join(lines))
    assert handlers.migrate(tmp_path, dry_run=True)["skipped_lines"] == 3
    result = handlers.migrate(tmp_path, dry_run=False)
    assert (result["rows"], result["skipped_lines"]) == (1, 3)
    flip_domain_locked(tmp_path, "calls", "sqlite")
    assert handlers.verify(tmp_path)["skipped_lines"] == 3
    assert handlers.retire(tmp_path)["skipped_saved"] == 3
    saved = tmp_path / handlers.SKIPPED_NAME
    assert saved.read_text().splitlines() == [
        "garbage",
        '{"command":"no ts"}',
        '{"torn"',
    ]
    assert saved.stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / CALLS_NAME).exists()
