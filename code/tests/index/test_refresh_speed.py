from __future__ import annotations

from varde_code.index.build import build
from varde_code.index.incremental import refresh
from varde_code.model import ExtractOutput


class Provider:
    def __init__(self):
        self.calls = []

    def extract(self, path, source, language):
        self.calls.append(path)
        return ExtractOutput()


def test_matching_metadata_reuses_stored_hash_without_reparsing(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    provider = Provider()
    build(root, provider)
    refresh(root, provider)
    provider.calls.clear()

    summary = refresh(root, provider)

    assert summary.reparsed == 0
    assert summary.unchanged == 1
    assert provider.calls == []
