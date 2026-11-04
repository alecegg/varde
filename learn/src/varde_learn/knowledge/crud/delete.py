"""Delete a concept document from a bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Never

from varde_learn.knowledge.crud import ConceptIoError, concept_path, path_is_contained
from varde_learn.knowledge.crud.update import _slug_lock


def _raise(error: Exception) -> Never:
    raise error


class DeleteError(Exception):
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


def delete(bundle: str | Path, slug: str) -> str:
    """Remove the concept at slug, returning the deleted slug."""
    bundle = Path(bundle)
    path = concept_path(bundle, slug)
    if path is None:
        error = ConceptIoError("invalid_slug", slug=slug)
        raise DeleteError(error.kind, str(error), slug=slug, source=error)
    try:
        with _slug_lock(bundle, slug):
            if not path_is_contained(bundle, path):
                error = ConceptIoError("invalid_slug", slug=slug)
                _raise(
                    DeleteError(
                        error.kind, str(error), slug=slug, path=path, source=error
                    )
                )
            try:
                path.unlink()
            except FileNotFoundError as exc:
                error = ConceptIoError("not_found", slug=slug, path=path, source=exc)
                raise DeleteError(
                    error.kind, str(error), slug=slug, path=path, source=error
                ) from exc
            except OSError as exc:
                error = ConceptIoError(
                    "delete_failed", slug=slug, path=path, source=exc
                )
                raise DeleteError(
                    error.kind, str(error), slug=slug, path=path, source=error
                ) from exc
    except DeleteError:
        raise
    except ConceptIoError as exc:
        raise DeleteError(
            exc.kind, str(exc), slug=slug, path=exc.path, source=exc
        ) from exc
    except OSError as exc:
        error = ConceptIoError("delete_failed", slug=slug, path=path, source=exc)
        raise DeleteError(
            error.kind, str(error), slug=slug, path=path, source=error
        ) from exc
    return slug


__all__ = ["DeleteError", "delete"]
