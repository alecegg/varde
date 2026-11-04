from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

import pytest
from varde_code.index import incremental
from varde_code.index.build import build
from varde_code.index.provenance import MAX_NON_GIT_AGE_SECONDS, read_built
from varde_code.model import ExtractOutput
from varde_code.query import dispatch
from varde_code.query.modes import index_service


class Extractor:
    def extract(self, path: Path, source: str, language: str) -> ExtractOutput:
        from varde_code.extract.entity import extract_file

        return extract_file(str(path), source, language)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(root), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def indexed(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("def f(): return 1\n")
    (root / "b.py").write_text("from a import f\n")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    summary = build(root, Extractor())
    return root, {"repoRoot": str(root), "dbPath": summary.db_path}


MODES = {
    "symbols_in_file": {"filePath": "a.py"},
    "dependencies": {"filePath": "a.py"},
    "hotspots": {},
}


@pytest.mark.parametrize("mode", sorted(MODES))
def test_fresh_index_returns_normally_with_provenance_meta(indexed, mode):
    root, params = indexed

    result = dispatch(mode, {**params, **MODES[mode]})

    assert result["ok"] is True
    meta = result["meta"]
    assert meta["built_head"] == _git(root, "rev-parse", "HEAD")
    assert meta["head"] == meta["built_head"]
    assert 0 <= meta["age_seconds"] < 60


@pytest.mark.parametrize("mode", sorted(MODES))
def test_edit_makes_every_freshness_mode_stale(indexed, mode):
    root, params = indexed
    (root / "a.py").write_text("def f(): return 2\n")

    result = dispatch(mode, {**params, **MODES[mode]})

    assert result["ok"] is False
    assert result["data"]["error"]["code"] == "index_stale"
    assert "varde map build" in result["data"]["error"]["message"]


def test_new_file_makes_index_stale(indexed):
    root, params = indexed
    (root / "c.py").write_text("x = 1\n")

    result = dispatch("hotspots", params)

    assert result["data"]["error"]["code"] == "index_stale"


def test_head_move_with_same_content_stays_fresh(indexed):
    root, params = indexed
    _git(root, "commit", "-q", "--allow-empty", "-m", "empty")

    result = dispatch("hotspots", params)

    assert result["ok"] is True
    assert result["meta"]["head"] != result["meta"]["built_head"]


def test_index_service_stays_unregistered(indexed):
    _root, params = indexed
    dispatch("hotspots", params)

    assert index_service() is None


def test_batch_reuses_fresh_result_and_reports_stale(indexed):
    root, params = indexed
    batch = {
        **params,
        "calls": [
            {"mode": "hotspots"},
            {"mode": "symbols_in_file", "filePath": "a.py"},
        ],
    }

    fresh = dispatch("batch", batch)
    assert [item["ok"] for item in fresh["data"]] == [True, True]

    (root / "a.py").write_text("def f(): return 3\n")
    stale = dispatch("batch", batch)
    assert [item["data"]["error"]["code"] for item in stale["data"]] == [
        "index_stale",
        "index_stale",
    ]


def test_refresh_after_edit_records_new_head_and_clears_staleness(indexed):
    root, params = indexed
    (root / "a.py").write_text("def f(): return 2\n")
    _git(root, "commit", "-qam", "edit")

    incremental.refresh(root, Extractor())

    built = read_built(params["dbPath"])
    assert built.built_head == _git(root, "rev-parse", "HEAD")
    assert dispatch("hotspots", params)["ok"] is True


def test_no_change_refresh_rewrites_head_only_when_it_moved(indexed):
    root, params = indexed
    db = Path(params["dbPath"])
    before = db.stat().st_mtime_ns
    incremental.refresh(root, Extractor())
    assert db.stat().st_mtime_ns == before

    _git(root, "commit", "-q", "--allow-empty", "-m", "empty")
    incremental.refresh(root, Extractor())

    assert read_built(db).built_head == _git(root, "rev-parse", "HEAD")


def test_non_git_build_records_empty_head(tmp_path, monkeypatch):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    summary = build(root, Extractor())

    built = read_built(summary.db_path)
    assert built.built_head == ""
    assert built.built_at is not None
    incremental.refresh(root, Extractor())
    assert read_built(summary.db_path).built_head == ""


def test_deleting_a_file_makes_index_stale(indexed):
    root, params = indexed
    (root / "b.py").unlink()

    assert dispatch("hotspots", params)["data"]["error"]["code"] == "index_stale"


def test_touch_without_edit_stays_fresh(indexed):
    root, params = indexed
    os.utime(root / "a.py", ns=(1, 1))

    assert dispatch("hotspots", params)["ok"] is True


def test_same_size_edit_is_stale(indexed):
    root, params = indexed
    (root / "a.py").write_text("def f(): return 9\n")

    assert dispatch("hotspots", params)["data"]["error"]["code"] == "index_stale"


def test_gitignored_file_stays_fresh_and_untracked_source_is_stale(indexed):
    root, params = indexed
    (root / ".gitignore").write_text("*.log\nbuild/\n")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-qm", "ignore")
    summary = build(root, Extractor())
    params = {**params, "dbPath": summary.db_path}
    (root / "debug.log").write_text("noise\n")
    (root / "build").mkdir()
    (root / "build" / "out.py").write_text("x = 1\n")

    assert dispatch("hotspots", params)["ok"] is True

    (root / "new.py").write_text("y = 2\n")
    assert dispatch("hotspots", params)["data"]["error"]["code"] == "index_stale"


def test_stash_restoring_identical_content_stays_fresh(indexed):
    root, params = indexed
    (root / "a.py").write_text("def f(): return 2\n")
    _git(root, "stash", "-q")
    assert (root / "a.py").read_text() == "def f(): return 1\n"

    assert dispatch("hotspots", params)["ok"] is True


def test_checkout_round_trip_stays_fresh(indexed):
    root, params = indexed
    _git(root, "checkout", "-q", "-b", "other")
    (root / "a.py").write_text("def f(): return 2\n")
    _git(root, "commit", "-qam", "other")
    _git(root, "checkout", "-q", "-")

    assert dispatch("hotspots", params)["ok"] is True


def _age_index(db: str, seconds: int) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE slice_meta SET value=value-? WHERE key='built_at'", (seconds,)
        )


def test_non_git_index_is_stale_after_the_age_limit(tmp_path, monkeypatch):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    summary = build(root, Extractor())
    params = {"repoRoot": str(root), "dbPath": summary.db_path}
    assert dispatch("hotspots", params)["ok"] is True

    _age_index(summary.db_path, MAX_NON_GIT_AGE_SECONDS + 60)
    assert dispatch("hotspots", params)["data"]["error"]["code"] == "index_stale"

    incremental.refresh(root, Extractor())
    assert dispatch("hotspots", params)["ok"] is True


def test_git_index_is_never_stale_by_age(indexed):
    _root, params = indexed
    _age_index(params["dbPath"], MAX_NON_GIT_AGE_SECONDS * 10)

    result = dispatch("hotspots", params)

    assert result["ok"] is True
    assert result["meta"]["age_seconds"] > MAX_NON_GIT_AGE_SECONDS
