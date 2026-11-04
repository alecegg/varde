"""Ephemeral frontmatter registry for one or more knowledge bundles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_learn.knowledge.bundle import is_reserved
from varde_learn.knowledge.walk import WalkError, visit_concepts


@dataclass(frozen=True)
class RegistryEntry:
    """A matching concept's slug, optional type, and complete frontmatter."""

    slug: str
    type_: str | None
    frontmatter: dict[str, Any]

    def as_dict(self) -> dict[str, object]:
        return {"slug": self.slug, "type": self.type_, "frontmatter": self.frontmatter}


class RegistryError(Exception):
    """A bundle traversal or concept parsing error."""

    def __init__(self, kind: str, path: Path, source: Exception) -> None:
        self.kind = kind
        self.path = path
        self.source = source
        super().__init__(f"{kind}: {path}: {source}")


def search(
    bundles: list[str | Path] | tuple[str | Path, ...],
    filters: list[tuple[str, str]] | tuple[tuple[str, str], ...],
) -> list[RegistryEntry]:
    """Return sorted exact-match results, with later bundles winning collisions."""
    from varde_learn.knowledge.crud import relative_slug

    merged: dict[str, RegistryEntry] = {}
    for value in bundles:
        bundle = Path(value)

        def collect(item: Any, bundle: Path = bundle) -> None:
            if not _matches_all(item.frontmatter, filters):
                return
            type_value = item.frontmatter.get("type")
            type_ = type_value if isinstance(type_value, str) and type_value else None
            slug = relative_slug(bundle, item.path)
            merged[slug] = RegistryEntry(slug, type_, item.frontmatter)

        try:
            visit_concepts(bundle, is_reserved, collect)
        except WalkError as exc:
            raise RegistryError(exc.kind, exc.path, exc.source) from exc
    return [merged[slug] for slug in sorted(merged)]


def _matches_all(
    frontmatter: dict[str, Any],
    filters: list[tuple[str, str]] | tuple[tuple[str, str], ...],
) -> bool:
    """Return whether each filter matches its field exactly."""
    return all(
        _field_matches(frontmatter.get(key), expected) for key, expected in filters
    )


def _field_matches(value: object, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    if isinstance(value, bool):
        return str(value).lower() == expected
    if isinstance(value, (int, float)):
        return str(value) == expected
    if isinstance(value, list):
        return any(_field_matches(item, expected) for item in value)
    return False


__all__ = ["RegistryEntry", "RegistryError", "search"]
