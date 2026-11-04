"""Path validation for decision evidence attachments."""

from __future__ import annotations

import stat
from pathlib import Path

MAX_EVIDENCE_BYTES = 5 * 1024 * 1024
EVIDENCE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".md", ".txt"}


def resolve_evidence_path(path: str, allowed_roots: tuple[Path, ...]) -> Path | None:
    """Return an allowed regular evidence file, or None when it fails policy."""
    candidate = Path(path)
    if not candidate.is_absolute():
        return None
    if candidate.suffix.lower() not in EVIDENCE_SUFFIXES:
        return None
    try:
        resolved = candidate.resolve(strict=True)
        metadata = candidate.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_EVIDENCE_BYTES:
            return None
        if not _is_allowed_path(candidate, resolved, allowed_roots):
            return None
    except OSError, RuntimeError, ValueError:
        return None
    return resolved


def _is_allowed_path(
    candidate: Path, resolved: Path, allowed_roots: tuple[Path, ...]
) -> bool:
    if ".." in candidate.parts:
        return False
    for root in allowed_roots:
        resolved_root = root.resolve()
        if not resolved.is_relative_to(resolved_root):
            continue
        if any(
            part.startswith(".") for part in resolved.relative_to(resolved_root).parts
        ):
            return False
        return not any(
            ancestor.is_symlink() and ancestor.resolve().is_relative_to(resolved_root)
            for ancestor in (candidate, *candidate.parents)
        )
    return False
