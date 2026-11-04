"""Filesystem side of the survey: bounded walk and file reads. No discovery logic."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from .survey import MAX_READ_BYTES

SKIP_DIRS = frozenset(
    {
        "node_modules", ".git", "dist", "build", "out", "target", "coverage",
        ".next", ".nuxt", ".svelte-kit", ".turbo", ".cache", ".venv", "venv",
        "__pycache__",
    }
)  # fmt: skip
MAX_FILES = 5000
MAX_SECONDS = 5.0


@dataclass(frozen=True)
class Walk:
    paths: list[str]
    sizes: dict[str, int]
    truncated: bool


def walk_project(
    root: Path, max_files: int = MAX_FILES, max_seconds: float = MAX_SECONDS
) -> Walk:
    """Relative posix paths under root, stopping at the file or time cap."""
    deadline = time.monotonic() + max_seconds
    paths: list[str] = []
    sizes: dict[str, int] = {}
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            if len(paths) >= max_files or time.monotonic() > deadline:
                return Walk(paths, sizes, True)
            full = Path(folder) / name
            rel = full.relative_to(root).as_posix()
            paths.append(rel)
            sizes[rel] = _size(full)
    return Walk(paths, sizes, False)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return MAX_READ_BYTES + 1


def read_texts(root: Path, wanted: list[str]) -> dict[str, str]:
    """Text of each wanted path; unreadable files are left out."""
    texts: dict[str, str] = {}
    for rel in wanted:
        try:
            texts[rel] = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return texts
