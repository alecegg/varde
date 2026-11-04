"""The pass reads the fast index read-only and refuses a stale or missing one."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from pass_support import (
    build_index,
    facts_by_path,
    path_class,
    prepare_env,
    write_repo,
)
from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.slice import IndexService
from varde_code.quality_pass.pass_ import QualityPassError, run_quality_pass
from varde_code.query import modes

FILES = {
    "src/app.py": "def run():\n    return 1\n",
    "tests/test_app.py": "def test_run():\n    assert True\n",
    "bench/tool.py": "def tool():\n    return 2\n",
    "vendor/lib.py": "def lib():\n    return 3\n",
    "notes.txt": "not source\n",
}


def test_file_list_and_path_classes_come_from_the_index_read_only(
    tmp_path, monkeypatch
):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, FILES)
    built = build_index(root)
    db_path = Path(built.db_path)
    before_db = db_path.read_bytes()
    before_names = {path.name for path in db_path.parent.iterdir()}

    summary = run_quality_pass(root, workers=1)

    assert summary.file_count == 4
    facts = facts_by_path(root)
    assert sorted(facts) == [
        "bench/tool.py",
        "src/app.py",
        "tests/test_app.py",
        "vendor/lib.py",
    ]
    # The pass reports the index's own generated path columns; pytest's tmp
    # directory name contains a test_ segment, so only the columns can be the
    # expected value here.
    with sqlite3.connect(db_path) as connection:
        index_rows = {
            row[0]: (bool(row[1]), bool(row[2]))
            for row in connection.execute(
                "SELECT path, is_test_path, is_tooling_path FROM files"
            )
        }
    for relative in facts:
        stored = path_class(root, relative)
        assert stored["test"] == index_rows[str(root / relative)][0]
        assert stored["tooling"] == index_rows[str(root / relative)][1]
    assert path_class(root, "tests/test_app.py")["test"] is True
    assert path_class(root, "bench/tool.py")["tooling"] is True
    assert path_class(root, "vendor/lib.py")["excluded"] is True
    assert (
        path_class(root, "vendor/lib.py")["exclusion_reason"]
        == "vendored directory convention"
    )

    assert db_path.read_bytes() == before_db
    added = {path.name for path in db_path.parent.iterdir()} - before_names
    assert added
    assert all(name.startswith(("quality-", ".quality-")) for name in added)


def test_pass_refuses_a_missing_index(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, {"src/app.py": "def run():\n    return 1\n"})

    with pytest.raises(QualityPassError) as error:
        run_quality_pass(root, workers=1)

    assert error.value.code == "index_missing"


def test_pass_refuses_a_stale_index(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, {"src/app.py": "def run():\n    return 1\n"})
    build_index(root)
    target = root / "src/app.py"
    target.write_text("def run():\n    return 2\n", encoding="utf-8")
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))

    with pytest.raises(QualityPassError) as error:
        run_quality_pass(root, workers=1)

    assert error.value.code == "index_stale"


def test_registered_index_service_is_freshened_before_the_pass(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, {"src/app.py": "def run():\n    return 1\n"})
    build_index(root)
    monkeypatch.setattr(
        modes,
        "_INDEX_SERVICE",
        IndexService(provider=CodeExtractionProvider()),
    )
    (root / "src/app.py").write_text("def run():\n    return 2\n", encoding="utf-8")

    summary = run_quality_pass(root, workers=1)

    assert summary.facts_recomputed == ("src/app.py",)
    assert facts_by_path(root)["src/app.py"]["tokens"] > 0
