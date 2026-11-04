"""Shared helpers for the scan-time quality pass tests."""

from __future__ import annotations

import json
from pathlib import Path

from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.build import build
from varde_code.quality_pass.pass_ import read_facts, read_measures
from varde_code.quality_pass.store import open_store, quality_store_path
from varde_code.query import modes


def prepare_env(monkeypatch, tmp_path: Path) -> Path:
    """Isolate the config dir and detach any registered index service."""
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(modes, "_INDEX_SERVICE", None)
    return tmp_path / "repo"


def write_repo(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def build_index(root: Path):
    return build(root, CodeExtractionProvider())


def refresh_index(root: Path) -> None:
    from varde_code.index.incremental import refresh

    refresh(root, CodeExtractionProvider())


def facts_by_path(root: Path) -> dict[str, dict]:
    return {record["path"]: record for record in read_facts(root)}


def measures_by_path(root: Path) -> dict[str, dict]:
    return {record["path"]: record for record in read_measures(root)}


def snapshot(root: Path) -> str:
    payload = {
        "facts": list(read_facts(root)),
        "measures": list(read_measures(root)),
    }
    return json.dumps(payload, sort_keys=True)


def path_class(root: Path, path: str) -> dict:
    with open_store(quality_store_path(root).parent) as store:
        record = store.get_path_class(path)
    assert record is not None, f"no path class stored for {path}"
    return record
