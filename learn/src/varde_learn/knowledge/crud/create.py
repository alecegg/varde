"""Create a validated concept document in a knowledge bundle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from varde_learn.knowledge.concept import Concept, ConceptMetadataError
from varde_learn.knowledge.crud import ConceptIoError, atomic_create, concept_path_or
from varde_learn.knowledge.frontmatter import FrontmatterError
from varde_learn.knowledge.occ import version


class CreateError(Exception):
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
class CreatedConcept:
    slug: str
    version: str


def create(bundle: str | Path, data: bytes, slug: str) -> CreatedConcept:
    """Validate data and create slug.md atomically; never overwrite."""
    bundle = Path(bundle)
    try:
        path = concept_path_or(bundle, slug)
    except ConceptIoError as exc:
        raise CreateError(
            exc.kind, str(exc), slug=slug, path=exc.path, source=exc
        ) from exc
    try:
        concept = Concept.from_bytes(data, slug)
        concept.validate_new_metadata()
    except FrontmatterError as exc:
        raise CreateError("invalid_concept", str(exc), slug=slug, source=exc) from exc
    except ConceptMetadataError as exc:
        raise CreateError(exc.code, str(exc), slug=slug, source=exc) from exc
    if path.parent != bundle:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CreateError(
                "create_dir_failed", str(exc), path=path.parent, source=exc
            ) from exc
    try:
        path = concept_path_or(bundle, slug)
        atomic_create(path, data)
    except FileExistsError as exc:
        raise CreateError(
            "already_exists",
            f"concept {slug!r} already exists in the bundle",
            slug=slug,
            path=path,
            source=exc,
        ) from exc
    except ConceptIoError as exc:
        raise CreateError(
            exc.kind, str(exc), slug=slug, path=exc.path, source=exc
        ) from exc
    except OSError as exc:
        raise CreateError("write_failed", str(exc), path=path, source=exc) from exc
    return CreatedConcept(slug, version(data))


__all__ = ["CreateError", "CreatedConcept", "create"]
