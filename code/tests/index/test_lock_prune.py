from __future__ import annotations

from pathlib import Path

import pytest
from varde_code import ApiError
from varde_code.index.build import build
from varde_code.index.incremental import refresh
from varde_code.index.prune import run_in
from varde_code.index.repo_lock import acquire, lock_path, probe
from varde_code.model import ExtractOutput


def test_repo_lock_serializes_and_releases(tmp_path: Path) -> None:
    db = tmp_path / "repo" / "index.db"
    held = acquire(db, timeout=1)
    assert lock_path(db).is_file()
    locked, guard = probe(db)
    assert locked is True
    assert guard is None
    held.close()
    locked, guard = probe(db)
    assert locked is False
    assert guard is not None
    guard.close()


def test_prune_dry_run_and_apply_only_remove_missing_sources(tmp_path: Path) -> None:
    roots = tmp_path / "code" / "repos-py"
    orphan = roots / "orphan-1"
    active = roots / "active-2"
    unknown = roots / "unknown-3"
    for folder in (orphan, active, unknown):
        folder.mkdir(parents=True)
        (folder / "index.db").write_bytes(b"index")
    (orphan / "source-root").write_text(str(tmp_path / "gone") + "\n")
    source = tmp_path / "source"
    source.mkdir()
    (active / "source-root").write_text(str(source) + "\n")

    preview = run_in(tmp_path, {})
    assert preview["counts"]["scanned"] == 3
    assert [item["reason"] for item in preview["wouldRemove"]] == ["source_missing"]
    assert orphan.exists()
    assert preview["counts"]["unknown"] == 1

    result = run_in(tmp_path, {"apply": True})
    assert len(result["removed"]) == 1
    assert not orphan.exists()
    assert active.exists() and unknown.exists()


def test_prune_rejects_invalid_input(tmp_path: Path) -> None:
    with pytest.raises(ApiError, match="invalid_input"):
        run_in(tmp_path, [])
    with pytest.raises(ApiError, match="non-negative integer"):
        run_in(tmp_path, {"unknownOlderThanDays": -1})


class EmptyProvider:
    def extract(self, path, source, language):
        return ExtractOutput()


def test_build_and_refresh_record_source_root_for_prune(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "main.py").write_text("pass\n", encoding="utf-8")
    config = tmp_path / "config"
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    provider = EmptyProvider()
    summary = build(root, provider)
    refresh(root, provider)
    folder = Path(summary.db_path).parent
    sidecar = folder / "source-root"
    assert sidecar.read_text(encoding="utf-8") == f"{root.resolve()}\n"

    import shutil

    shutil.rmtree(root)
    result = run_in(config, {})
    assert [item["reason"] for item in result["wouldRemove"]] == ["source_missing"]
