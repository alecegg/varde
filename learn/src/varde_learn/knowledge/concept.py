"""Core concept document model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from varde_learn.knowledge.frontmatter import parse


@dataclass
class Concept:
    slug: str
    frontmatter: dict[str, Any]
    body: str

    @classmethod
    def from_bytes(cls, data: bytes, slug: str) -> Concept:
        frontmatter, body = parse(data)
        return cls(slug, frontmatter, body)

    def validate_new_metadata(self) -> None:
        description = self.frontmatter.get("description")
        if "description" not in self.frontmatter:
            raise ConceptMetadataError(
                "concept description is required", "missing_description"
            )
        if not isinstance(description, str) or not description.strip():
            raise ConceptMetadataError(
                "concept description must be a non-empty string", "invalid_description"
            )
        if "aliases" in self.frontmatter:
            aliases = self.frontmatter["aliases"]
            if not isinstance(aliases, list) or any(
                not isinstance(item, str) or not item.strip() for item in aliases
            ):
                raise ConceptMetadataError(
                    "concept aliases must be a sequence of non-empty strings",
                    "invalid_aliases",
                )


class ConceptMetadataError(ValueError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def slug_from_filename(filename: str) -> str | None:
    return filename.removesuffix(".md") if filename.endswith(".md") else None
