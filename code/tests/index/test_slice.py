from __future__ import annotations

import os
import sqlite3
from typing import Any, cast

from varde_code.git import run_git
from varde_code.index.db import SCHEMA_VERSION, build_version_fingerprint, initialize
from varde_code.index.slice import (
    IndexService,
    Scope,
    Slice,
    check_content_fresh,
    check_fresh,
    dump_state,
    ensure_fresh,
    reverse_dependent_scope,
)


def _fresh_index(db_path, source):
    connection = initialize(db_path)
    metadata = source.stat()
    connection.execute(
        "INSERT INTO files(path, mtime, size, content_hash, rev) "
        "VALUES (?, ?, ?, '', 1)",
        (str(source), metadata.st_mtime_ns, metadata.st_size),
    )
    connection.execute("INSERT INTO slice_meta(key, value) VALUES ('next_rev', 2)")
    connection.execute(
        "UPDATE slice_meta SET value = ? WHERE key = 'build_version'",
        (build_version_fingerprint(),),
    )
    for name in ("imports", "edges", "global"):
        connection.execute(
            "INSERT INTO slice_state VALUES (?, 1, ?)", (name, SCHEMA_VERSION)
        )
    connection.commit()
    connection.close()


def test_check_fresh_validates_schema_file_set_and_requested_ledger(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "main.py"
    source.write_text("print('hello')\n")
    db_path = tmp_path / "index.db"
    _fresh_index(db_path, source)

    assert check_fresh(db_path, root)
    assert check_fresh(db_path, root, (Slice.RAW,))
    assert not check_fresh(
        db_path, root, (Slice.EDGES,), Scope.for_file(tmp_path / "outside.py")
    )

    source.write_text("print('changed')\n")
    os.utime(
        source, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns + 1_000_000)
    )
    assert not check_fresh(db_path, root)


def test_dump_state_is_read_only_and_reports_missing_and_stale(tmp_path):
    missing = dump_state(db_path=tmp_path / "missing.db")
    assert missing["db"] == "missing"

    root = tmp_path / "repo"
    root.mkdir()
    source = root / "main.py"
    source.write_text("pass\n")
    db_path = tmp_path / "index.db"
    _fresh_index(db_path, source)
    state = dump_state(db_path=db_path)
    assert state["max_rev"] == 1
    assert state["next_rev"] == 2
    slices = cast("dict[str, Any]", state["slices"])
    assert slices["global"] == {"built_through_rev": 1, "stale": False}


def test_reverse_dependent_scope_includes_resolved_callers_and_caps(tmp_path):
    connection = initialize(tmp_path / "index.db")
    connection.executemany(
        "INSERT INTO files(id, path) VALUES (?, ?)",
        [(1, "a.py"), (2, "b.py"), (3, "c.py")],
    )
    connection.execute(
        "INSERT INTO resolved_edges(from_file_id, to_file_id, kind, resolved) "
        "VALUES (2, 1, 0, 1), (3, 2, 0, 1)"
    )
    assert reverse_dependent_scope(connection, [1]) == {1, 2}
    assert reverse_dependent_scope(connection, []) == set()
    connection.close()


def test_index_service_uses_shared_protocol_signatures(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    service = IndexService()
    monkeypatch.setattr(
        "varde_code.index.slice.repo_db_path", lambda _root: tmp_path / "db"
    )
    assert service.repo_db_path(root) == tmp_path / "db"
    assert service.check_fresh(root) is False
    assert service.dump_state(root)["db"] == "missing"

    calls = []
    ensure_fresh(tmp_path / "db", root, freshen=lambda *args: calls.append(args))
    assert calls == [(root, (Slice.GLOBAL,), Scope.repo())]


def test_check_fresh_accepts_index_built_before_gitignore_discovery(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    run_git(["init", "-q"], root)
    (root / ".gitignore").write_text("ignored/\n")
    (root / "ignored").mkdir()
    ignored = root / "ignored" / "generated.py"
    ignored.write_text("x = 1\n")
    source = root / "main.py"
    source.write_text("print('hello')\n")
    gitignore = root / ".gitignore"
    db_path = tmp_path / "index.db"
    _fresh_index(db_path, source)
    connection = sqlite3.connect(db_path)
    for extra in (ignored, gitignore):
        metadata = extra.stat()
        connection.execute(
            "INSERT INTO files(path, mtime, size, content_hash, rev) "
            "VALUES (?, ?, ?, '', 1)",
            (str(extra), metadata.st_mtime_ns, metadata.st_size),
        )
    connection.commit()
    connection.close()

    assert check_content_fresh(db_path, root)


def test_strict_check_fresh_is_stale_once_for_pre_gitignore_index(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    run_git(["init", "-q"], root)
    (root / ".gitignore").write_text("ignored/\n")
    (root / "ignored").mkdir()
    ignored = root / "ignored" / "generated.py"
    ignored.write_text("x = 1\n")
    source = root / "main.py"
    source.write_text("print('hello')\n")
    db_path = tmp_path / "index.db"
    _fresh_index(db_path, source)
    connection = sqlite3.connect(db_path)
    for extra in (ignored, root / ".gitignore"):
        metadata = extra.stat()
        connection.execute(
            "INSERT INTO files(path, mtime, size, content_hash, rev) "
            "VALUES (?, ?, ?, '', 1)",
            (str(extra), metadata.st_mtime_ns, metadata.st_size),
        )
    connection.commit()
    connection.close()

    # Documented one-time rebuild: the strict check still counts ignored rows.
    assert not check_fresh(db_path, root)
    assert check_content_fresh(db_path, root)
