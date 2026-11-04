"""Bring the repo's single index up to date before generating packs."""

from __future__ import annotations

from pathlib import Path

from varde_code.index.build import build
from varde_code.index.incremental import refresh
from varde_code.index.paths import repo_db_path
from varde_code.seams import ExtractionProvider


def ensure_index(root: Path, extractor: ExtractionProvider) -> Path:
    """Refresh the existing index in place, or build it when missing.

    ``refresh`` rebuilds in place when the schema or build version changed; no
    copy or temporary index is ever created.
    """
    if repo_db_path(root).is_file():
        refresh(root, extractor)
    else:
        build(root, extractor)
    return repo_db_path(root)
