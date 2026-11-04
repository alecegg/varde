"""List concept documents in a bundle."""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from pathlib import Path

from varde_learn.knowledge.crud import ConceptIoError, relative_slug
from varde_learn.knowledge.frontmatter import FrontmatterError
from varde_learn.knowledge.walk import WalkedFile, WalkError, visit_concepts


class ListError(Exception):
    def __init__(
        self,
        kind: str,
        message: str,
        *,
        path: Path | None = None,
        source: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.path = path
        self.source = source


@dataclass(frozen=True)
class ListedConcept:
    slug: str
    type_: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {"slug": self.slug, "type": self.type_}


def list(
    bundle: str | Path, include_deprecated: bool = False
) -> builtins.list[ListedConcept]:
    """List sorted concept slugs, excluding reserved docs and deprecated entries.

    Deprecated entries are excluded by default.
    """
    bundle = Path(bundle)
    concepts: builtins.list[ListedConcept] = []

    def collect(item: WalkedFile) -> None:
        frontmatter = item.frontmatter
        type_value = frontmatter.get("type")
        type_ = type_value if isinstance(type_value, str) and type_value else None
        if not include_deprecated and frontmatter.get("status") == "deprecated":
            return
        concepts.append(ListedConcept(relative_slug(bundle, item.path), type_))

    try:
        visit_concepts(bundle, lambda name: name in {"index.md", "log.md"}, collect)
    except WalkError as exc:
        if exc.kind == "read_dir_failed":
            raise ListError(
                "read_dir_failed", str(exc), path=exc.path, source=exc.source
            ) from exc
        if exc.kind == "read_failed":
            if not isinstance(exc.source, OSError):
                raise AssertionError("read failure must contain an OSError") from exc
            io_error = ConceptIoError("read_failed", path=exc.path, source=exc.source)
            raise ListError(
                "io", str(io_error), path=exc.path, source=io_error
            ) from exc
        if isinstance(exc.source, FrontmatterError):
            raise ListError(
                "invalid_concept", str(exc), path=exc.path, source=exc.source
            ) from exc
        raise ListError(
            "invalid_concept", str(exc), path=exc.path, source=exc.source
        ) from exc
    return sorted(concepts, key=lambda item: item.slug)


__all__ = ["ListError", "ListedConcept", "list"]
