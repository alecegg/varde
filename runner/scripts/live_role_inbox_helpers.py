"""Pure assertions and snapshots used by the live role-inbox drill."""

from __future__ import annotations

import fnmatch
import hashlib
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def unread_snapshot(rows: Mapping[str, Iterable[str]]) -> dict[str, tuple[str, ...]]:
    """Normalize per-holder unread IDs for stable comparison and transcripts."""
    return {
        holder: tuple(sorted(set(message_ids))) for holder, message_ids in rows.items()
    }


def same_unread_set(before: Iterable[str], after: Iterable[str]) -> bool:
    """Whether a rollback retained the same unread message IDs."""
    return set(before) == set(after)


def one_claim(results: Iterable[Mapping[str, Any] | None]) -> Mapping[str, Any]:
    """Return the sole claimed work item, rejecting zero or duplicate claims."""
    claims = [result for result in results if result is not None]
    if len(claims) != 1:
        raise AssertionError(f"expected one claim, observed {len(claims)}")
    return claims[0]


def assert_clean_restart(log: str) -> None:
    """Reject startup logs that indicate an interrupted message-store flip."""
    errors = (
        "interrupted store mode flip",
        "store-version mismatch",
        "schema version",
        "newer than supported",
    )
    found = next((error for error in errors if error in log.lower()), None)
    if found is not None:
        raise AssertionError(f"runner restart reported {found}")


def tree_digest(root: Path, ignored_paths: frozenset[str] = frozenset()) -> str:
    """Hash paths and contents, skipping known volatile paths and descendants."""
    digest = hashlib.sha256()
    for directory, names, files in os.walk(root, followlinks=False):
        names.sort()
        files.sort()
        base = Path(directory)
        for name in names + files:
            path = base / name
            relative = path.relative_to(root).as_posix()
            if any(
                fnmatch.fnmatchcase(relative, ignored)
                if "*" in ignored
                else relative == ignored or relative.startswith(f"{ignored}/")
                for ignored in ignored_paths
            ):
                continue
            digest.update(relative.encode())
            digest.update(b"\0")
            if path.is_symlink():
                digest.update(b"link\0")
                digest.update(os.readlink(path).encode())
            elif path.is_file():
                digest.update(b"file\0")
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
            else:
                digest.update(b"dir\0")
    return digest.hexdigest()
