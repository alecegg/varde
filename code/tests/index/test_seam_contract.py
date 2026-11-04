from __future__ import annotations

import inspect
from pathlib import Path
from typing import ClassVar

from varde_code import index
from varde_code.index.files import DefaultFileWalker
from varde_code.index.persist.graph import SqliteGraphCache
from varde_code.index.slice import IndexService
from varde_code.seams import (
    FileWalker,
    GraphCache,
)
from varde_code.seams import (
    IndexService as IndexServiceProtocol,
)


def _assert_methods_compatible(
    implementation: type, protocol: type, names: tuple[str, ...]
) -> None:
    for name in names:
        actual = inspect.signature(getattr(implementation, name))
        expected = inspect.signature(getattr(protocol, name))
        assert tuple(actual.parameters) == tuple(expected.parameters)


def test_index_package_registers_implementations_for_core_seams() -> None:
    assert index.FileWalker is DefaultFileWalker
    assert index.IndexService is IndexService
    assert index.GraphCache is SqliteGraphCache
    _assert_methods_compatible(
        DefaultFileWalker,
        FileWalker,
        ("list_source_listing", "is_vcs_internal"),
    )
    _assert_methods_compatible(
        IndexService,
        IndexServiceProtocol,
        ("ensure_fresh", "check_fresh", "dump_state", "repo_db_path"),
    )
    _assert_methods_compatible(SqliteGraphCache, GraphCache, ("read", "write"))


def test_index_service_wires_provider_freshener_and_incremental_refresh(
    tmp_path, monkeypatch
) -> None:
    from varde_code.model import ExtractOutput

    root = tmp_path / "repo"
    root.mkdir()
    source = root / "main.py"
    source.write_text("pass\n", encoding="utf-8")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))

    class Provider:
        calls: ClassVar[list[Path]] = []

        def extract(self, path: Path, source: str, language: str) -> ExtractOutput:
            self.calls.append(path)
            return ExtractOutput()

    provider = Provider()
    service = IndexService(provider)
    service.ensure_fresh(root)
    assert provider.calls == [source]

    provider.calls.clear()
    source.write_text("pass # changed\n", encoding="utf-8")
    service.ensure_fresh(root)
    assert provider.calls == [source]
