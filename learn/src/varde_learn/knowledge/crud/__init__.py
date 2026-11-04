"""Concept CRUD helpers and operations for a knowledge bundle."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


class ConceptIoError(OSError):
    """Shared path and I/O error used by concept CRUD operations."""

    def __init__(
        self,
        kind: str,
        *,
        slug: str | None = None,
        path: Path | None = None,
        source: OSError | None = None,
    ) -> None:
        self.kind = kind
        self.slug = slug
        self.path = path
        self.source = source
        if kind == "invalid_slug":
            message = f"invalid slug {slug!r}: must be kebab-case path segments"
        elif kind == "not_found":
            message = f"concept {slug!r} not found in the bundle"
        elif kind == "conflict":
            message = f"version conflict for {slug!r}"
        else:
            message = f"failed to {kind.replace('_', ' ')} {path}: {source}"
        super().__init__(message)


def validate_slug(slug: str) -> bool:
    """Return whether slug is one or more kebab-case path segments."""
    if not slug or "\\" in slug:
        return False
    return all(_valid_segment(segment) for segment in slug.split("/"))


def _valid_segment(segment: str) -> bool:
    if not segment or segment[0] not in "abcdefghijklmnopqrstuvwxyz0123456789":
        return False
    previous_dash = False
    for char in segment[1:]:
        if char == "-":
            if previous_dash:
                return False
            previous_dash = True
        elif char in "abcdefghijklmnopqrstuvwxyz0123456789":
            previous_dash = False
        else:
            return False
    return not previous_dash


def concept_path(bundle: str | Path, slug: str) -> Path | None:
    """Return the validated bundle path for slug, or ``None`` if malformed."""
    if not validate_slug(slug):
        return None
    return Path(bundle).joinpath(*slug.split("/")).with_suffix(".md")


def concept_path_or(bundle: str | Path, slug: str) -> Path:
    path = concept_path(bundle, slug)
    if path is None:
        raise ConceptIoError("invalid_slug", slug=slug)
    try:
        contained = path_is_contained(Path(bundle), path)
    except OSError as exc:
        raise ConceptIoError("read_failed", path=Path(bundle), source=exc) from exc
    if not contained:
        raise ConceptIoError("invalid_slug", slug=slug)
    return path


def path_is_contained(bundle: Path, candidate: Path) -> bool:
    """Check existing symlink components resolve beneath the bundle root."""
    try:
        resolved_bundle = bundle.resolve(strict=True)
    except FileNotFoundError:
        return True
    try:
        relative = candidate.relative_to(bundle)
    except ValueError:
        return False
    current = bundle
    for component in relative.parts:
        current = current / component
        try:
            is_link = current.is_symlink()
            current.lstat()
        except FileNotFoundError:
            return True
        if is_link:
            try:
                resolved = current.resolve(strict=True)
            except FileNotFoundError:
                return False
            if not resolved.is_relative_to(resolved_bundle):
                return False
    return True


def relative_slug(bundle: str | Path, path: str | Path) -> str:
    """Derive a slash-separated bundle-relative slug from a markdown path."""
    bundle_path = Path(bundle)
    file_path = Path(path)
    try:
        relative = file_path.relative_to(bundle_path)
    except ValueError:
        relative = file_path
    value = str(relative).replace(os.sep, "/")
    return value.removesuffix(".md")


def atomic_create(path: Path, data: bytes) -> None:
    """Create path via a same-directory stage without replacing an existing file."""
    fd, stage_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    stage = Path(stage_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(stage, path)
    finally:
        stage.unlink(missing_ok=True)


__all__ = [
    "ConceptIoError",
    "atomic_create",
    "concept_path",
    "concept_path_or",
    "path_is_contained",
    "relative_slug",
    "validate_slug",
]
