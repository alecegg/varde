"""Resolve the configured working directory for a project or nested cwd."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_working_dir(start: str | Path) -> Path:
    """Resolve the configured working directory for a project or nested cwd."""
    return resolve_working_dir_with_source(start)[0]


def resolve_working_dir_with_source(start: str | Path) -> tuple[Path, bool]:
    """Resolve the working directory and whether it came from a known project."""
    from varde_learn.knowledge.memory import MemoryPaths, find_root

    path = Path(start)
    root = find_root(path)
    return MemoryPaths.resolve(root or path).working.path, root is not None or bool(
        os.environ.get("VARDE_WORKING_DIR")
    )
