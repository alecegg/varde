"""Keep the learn store's machine files out of a git-tracked learn root."""

from __future__ import annotations

from pathlib import Path

from varde_data.locking import atomic_write

IGNORED_PATTERNS = (
    "learn.sqlite3*",
    "store-mode.json",
    "store-mode.lock",
)


def missing_patterns(existing: str) -> list[str]:
    """Return the patterns not yet listed in a ``.gitignore`` text."""
    known = {line.strip() for line in existing.splitlines()}
    return [pattern for pattern in IGNORED_PATTERNS if pattern not in known]


def ensure_ignored(root: Path) -> None:
    """Append the missing patterns to an existing ``.gitignore``; never create one."""
    path = root / ".gitignore"
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    missing = missing_patterns(existing)
    if not missing:
        return
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    text = existing + prefix + "\n".join(missing) + "\n"
    atomic_write(path, text.encode(), mode=0o644)
