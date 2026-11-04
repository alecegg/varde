"""Read a concept document and its current OCC version."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_learn.knowledge.concept import Concept
from varde_learn.knowledge.crud import ConceptIoError, concept_path_or
from varde_learn.knowledge.frontmatter import FrontmatterError
from varde_learn.knowledge.occ import version


class ShowError(Exception):
    def __init__(
        self,
        kind: str,
        message: str,
        *,
        slug: str | None = None,
        path: Path | None = None,
        source: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.slug = slug
        self.path = path
        self.source = source


@dataclass(frozen=True)
class ShownConcept:
    slug: str
    version: str
    frontmatter: dict[str, Any]
    body: str


def show(bundle: str | Path, slug: str) -> ShownConcept:
    """Show a concept by validated slug."""
    try:
        path = concept_path_or(bundle, slug)
    except ConceptIoError as exc:
        raise ShowError(
            exc.kind, str(exc), slug=slug, path=exc.path, source=exc
        ) from exc
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise ShowError(
            "not_found",
            f"concept {slug!r} not found in the bundle",
            slug=slug,
            path=path,
            source=exc,
        ) from exc
    except OSError as exc:
        raise ShowError(
            "read_failed", str(exc), slug=slug, path=path, source=exc
        ) from exc
    try:
        concept = Concept.from_bytes(data, slug)
    except FrontmatterError as exc:
        raise ShowError(
            "invalid_concept", str(exc), slug=slug, path=path, source=exc
        ) from exc
    return ShownConcept(slug, version(data), concept.frontmatter, concept.body)


__all__ = ["ShowError", "ShownConcept", "show"]
