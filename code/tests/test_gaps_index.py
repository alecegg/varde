from __future__ import annotations

import sqlite3
from pathlib import Path

from varde_code.index import paths as index_paths
from varde_code.index.build import build


class NeverExtract:
    def extract(self, path: Path, source: str, language: str):
        raise AssertionError(f"unexpected extraction for {path}")


def _persisted_diagnostics(repo: Path) -> list[str]:
    with sqlite3.connect(index_paths.repo_db_path(repo)) as connection:
        rows = connection.execute("SELECT message FROM diagnostics ORDER BY id")
        return [row[0] for row in rows]


def test_index_skips_invalid_utf8_with_diagnostic(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "binary.ts").write_bytes(b"const word = '\xff';")
    monkeypatch.setattr(index_paths, "varde_config_dir", lambda: tmp_path / "config")

    summary = build(repo, NeverExtract())

    assert summary.entities == 0
    assert summary.symbols == 0
    assert _persisted_diagnostics(repo) == ["binary or non-UTF-8 — skipped"]
    assert "binary or non-UTF-8 — skipped" in capsys.readouterr().err


def test_index_skips_minified_source_with_diagnostic(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "bundle.js").write_text("x" * 2500, encoding="utf-8")
    monkeypatch.setattr(index_paths, "varde_config_dir", lambda: tmp_path / "config")

    summary = build(repo, NeverExtract())

    assert summary.entities == 0
    assert summary.symbols == 0
    assert _persisted_diagnostics(repo) == ["minified/generated source — skipped"]


def test_extraction_provider_preserves_parse_error_diagnostic(tmp_path: Path):
    from varde_code.extract.provider import CodeExtractionProvider

    source = tmp_path / "broken.ts"
    output = CodeExtractionProvider().extract(
        source, "function broken( {", "typescript"
    )

    assert [item.message for item in output.diagnostics] == [
        "syntax error — partial extract kept"
    ]
