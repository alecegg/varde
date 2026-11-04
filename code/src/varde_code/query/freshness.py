"""Source-root identity checks for explicit query database paths."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def source_root_mismatch(db_path: str, repo_root: str) -> bool:
    """Return whether an indexed database belongs to a different repo root."""
    try:
        with sqlite3.connect(Path(db_path).resolve()) as db:
            row = db.execute(
                "SELECT value FROM slice_meta WHERE key='source_root'"
            ).fetchone()
    except sqlite3.Error:
        return False
    return row is None or row[0] != _repo_identity(Path(repo_root))


def _repo_identity(repo_root: Path) -> int:
    canonical = repo_root.resolve()
    value = 0xCBF29CE484222325
    for byte in str(canonical).encode():
        value ^= byte
        value = value * 0x100000001B3 & 0xFFFFFFFFFFFFFFFF
    return value if value < 0x8000000000000000 else value - 0x10000000000000000
