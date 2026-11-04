"""Content and HEAD staleness for explicit-database index queries."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from varde_code.index.provenance import current_head, non_git_age_expired, read_built
from varde_code.index.slice import check_content_fresh

STALE_MESSAGE = (
    "index is out of date with the source tree (or, outside git, older than "
    "7 days); run `varde map build` (find_pattern needs no index)"
)


def content_stale(db_path: str, root: str, batch_cache: dict | None = None) -> bool:
    """Whether the index is stale: real content changes, or a non-git age-out.

    Git repos are never stale by HEAD or age; those only appear in meta.
    Inside a batch, a fresh result is reused for the remaining calls.
    """
    key = (db_path, root)
    if batch_cache is not None and batch_cache.get(key):
        return False
    fresh = check_content_fresh(db_path, root) and not non_git_age_expired(
        read_built(db_path), current_head(Path(root))
    )
    if fresh and batch_cache is not None:
        batch_cache[key] = True
    return not fresh


def provenance_meta(db_path: str, root: str) -> dict[str, Any]:
    """Return ``built_head``, ``head`` and ``age_seconds`` for response meta."""
    built = read_built(db_path)
    age = None if built.built_at is None else max(0, int(time.time()) - built.built_at)
    return {
        "built_head": built.built_head,
        "head": current_head(Path(root)),
        "age_seconds": age,
    }
