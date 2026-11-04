"""Stable code-module boundaries.

Published signatures:
* ``FileWalker.list_source_listing(root: Path) -> list[Path]`` and
  ``FileWalker.is_vcs_internal(path: Path) -> bool``.
* ``IndexService.ensure_fresh(root: Path) -> None``,
  ``check_fresh(root: Path, scope: object = None) -> bool``,
  ``dump_state(root: Path) -> dict[str, object]`` and
  ``repo_db_path(root: Path) -> Path``.
* ``ExtractionProvider.extract(path: Path, source: str, language: str) ->
  ExtractOutput``.
* ``GraphCache.read(db_path: Path, rev: int) -> Graph | None`` and
  ``write(db_path: Path, graph: Graph, rev: int) -> None``.

Implementations belong to the index and extract packages. These protocols
keep their dependencies pointed at the shared code package.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .graph_model import Graph
from .model import ExtractOutput


class FileWalker(Protocol):
    def list_source_listing(self, root: Path) -> list[Path]: ...

    def is_vcs_internal(self, path: Path) -> bool: ...


class IndexService(Protocol):
    def ensure_fresh(self, root: Path) -> None: ...

    def check_fresh(self, root: Path, scope: object = None) -> bool: ...

    def dump_state(self, root: Path) -> dict[str, object]: ...

    def repo_db_path(self, root: Path) -> Path: ...


class ExtractionProvider(Protocol):
    def extract(self, path: Path, source: str, language: str) -> ExtractOutput: ...


class GraphCache(Protocol):
    def read(self, db_path: Path, rev: int) -> Graph | None: ...

    def write(self, db_path: Path, graph: Graph, rev: int) -> None: ...
