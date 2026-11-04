from __future__ import annotations

import subprocess
from pathlib import Path

from varde_code.index import incremental
from varde_code.index.build import build
from varde_code.model import ExtractOutput


class Provider:
    def __init__(self) -> None:
        self.calls = []

    def extract(self, path: Path, source: str, language: str) -> ExtractOutput:
        self.calls.append(path)
        return ExtractOutput()


def test_no_change_refresh_returns_summary_without_full_refresh(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "main.py"
    source.write_text("pass\n", encoding="utf-8")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    provider = Provider()
    initial = build(root, provider)
    before = Path(initial.db_path).read_bytes()

    def unexpected_refresh(*_args, **_kwargs):
        raise AssertionError("unchanged refresh must return before incremental work")

    monkeypatch.setattr(incremental, "_refresh_changes", unexpected_refresh)
    summary = incremental.refresh(root, provider)

    assert provider.calls == [source]
    assert summary.db_path == initial.db_path
    assert (summary.entities, summary.symbols, summary.diagnostics) == (
        initial.entities,
        initial.symbols,
        initial.diagnostics,
    )
    assert (summary.unchanged, summary.reparsed, summary.changed_files) == (1, 0, ())
    assert Path(initial.db_path).read_bytes() == before


def test_refresh_reparses_changed_files_in_git_worktrees(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "main.py"
    source.write_text("pass\n", encoding="utf-8")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    provider = Provider()
    initial = build(root, provider)
    source.write_text("pass  # changed\n", encoding="utf-8")

    summary = incremental.refresh(root, provider)
    assert summary.db_path == initial.db_path
    assert summary.reparsed == 1
    assert summary.changed_files == (str(source),)

    subprocess.run(["git", "init", "-q", str(root)], check=True)  # noqa: S603,S607, RUF100 - Initializes a temporary repository using system git.
    build(root, provider)
    source.write_text("pass  # changed again\n", encoding="utf-8")
    summary = incremental.refresh(root, provider)
    assert summary.reparsed == 1
    assert summary.changed_files == (str(source),)
