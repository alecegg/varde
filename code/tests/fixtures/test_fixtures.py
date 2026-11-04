from __future__ import annotations

import json
from pathlib import Path

import pytest

from varde_code.index.build import build
from varde_code.extract.provider import CodeExtractionProvider

FIXTURES = Path(__file__).parent
REPOSITORIES = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))["repos"]


@pytest.mark.parametrize("name", REPOSITORIES)
def test_fixture_repositories_build_native_indexes(name, tmp_path, monkeypatch):
    repo = FIXTURES / "repos" / name
    assert repo.is_dir()
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))

    summary = build(repo, CodeExtractionProvider())

    assert summary.symbols > 0
