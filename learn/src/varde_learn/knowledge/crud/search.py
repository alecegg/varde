"""In-process lexical search across concept bundles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_learn.knowledge.bundle import is_reserved
from varde_learn.knowledge.walk import WalkedFile, visit_concepts

SLUG_WEIGHT = 3
TITLE_WEIGHT = 5
ALIASES_WEIGHT = 6
TAGS_WEIGHT = 4
OTHER_FIELD_WEIGHT = 2
HEADING_WEIGHT = 4
CHUNK_BODY_WEIGHT = 1
CHUNK_PREVIEW_LEN = 180
FALLBACK_PREVIEW_LEN = 200
DEFAULT_LIMIT = 20


@dataclass(frozen=True)
class TextSearchResult:
    slug: str
    type_: str | None
    score: int
    preview: str

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "slug": self.slug,
            "type": self.type_,
            "score": self.score,
            "preview": self.preview,
        }


def search_text(
    bundles: list[str | Path] | tuple[str | Path, ...],
    query: str,
    limit: int = DEFAULT_LIMIT,
) -> list[TextSearchResult]:
    """Return lexically ranked concepts, with later bundles winning slug collisions."""
    return search_text_matching(bundles, query, (), limit)


def search_text_matching(
    bundles: list[str | Path] | tuple[str | Path, ...],
    query: str,
    filters: list[tuple[str, str]] | tuple[tuple[str, str], ...],
    limit: int = DEFAULT_LIMIT,
) -> list[TextSearchResult]:
    terms = query_terms(query)
    if not terms:
        return []
    merged: dict[str, TextSearchResult] = {}

    def collect(bundle: Path, file: WalkedFile) -> None:
        result = _score_file(bundle, file, filters, terms)
        if result is not None:
            merged[result.slug] = result

    for value in bundles:
        bundle = Path(value)
        visit_concepts(
            bundle, is_reserved, lambda file, bundle=bundle: collect(bundle, file)
        )
    return sorted(merged.values(), key=lambda result: (-result.score, result.slug))[
        : max(0, limit)
    ]


def _score_file(
    bundle: Path,
    file: WalkedFile,
    filters: list[tuple[str, str]] | tuple[tuple[str, str], ...],
    terms: list[str],
) -> TextSearchResult | None:
    if not _matches_all(file.frontmatter, filters):
        return None
    type_value = file.frontmatter.get("type")
    type_ = type_value if isinstance(type_value, str) and type_value else None
    relative = file.path.relative_to(bundle)
    slug = str(relative).replace("\\", "/")
    slug = slug.removesuffix(".md")
    score = score_text(slug, terms, SLUG_WEIGHT)
    score += _score_frontmatter(file.frontmatter, terms)
    body_score, preview = score_body(file.body, terms)
    score += body_score
    return TextSearchResult(slug, type_, score, preview) if score > 0 else None


def _matches_all(
    frontmatter: dict[str, Any],
    filters: list[tuple[str, str]] | tuple[tuple[str, str], ...],
) -> bool:
    return all(
        _field_matches(frontmatter.get(key), expected) for key, expected in filters
    )


def _field_matches(value: Any, expected: str) -> bool:
    if isinstance(value, list):
        return any(_field_matches(item, expected) for item in value)
    if isinstance(value, (str, bool, int, float)):
        return _scalar_text(value) == expected
    return False


def _scalar_text(value: str | bool | float) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _score_frontmatter(frontmatter: dict[str, Any], terms: list[str]) -> int:
    return sum(
        _score_value(value, terms, field_weight(key))
        for key, value in frontmatter.items()
        if isinstance(key, str)
    )


def field_weight(field: str) -> int:
    return {"title": TITLE_WEIGHT, "aliases": ALIASES_WEIGHT, "tags": TAGS_WEIGHT}.get(
        field, OTHER_FIELD_WEIGHT
    )


def _normalize_text(value: str) -> str:
    return " ".join(
        "".join(char.lower() if char.isalnum() else " " for char in value).split()
    )


def query_terms(query: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for term in _normalize_text(query).split():
        if len(term) >= 2 and term not in seen:
            seen.add(term)
            terms.append(term)
    return terms


def score_text(text: str, terms: list[str], weight: int) -> int:
    normalized = _normalize_text(text)
    return sum(weight for term in terms if term in normalized)


def _score_value(value: Any, terms: list[str], weight: int) -> int:
    flattened = " ".join(_flatten_value(value))
    return score_text(flattened, terms, weight)


def _flatten_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (bool, int, float)):
        return [_scalar_text(value)]
    if isinstance(value, list):
        return [part for item in value for part in _flatten_value(item)]
    if isinstance(value, dict):
        return [part for item in value.values() for part in _flatten_value(item)]
    return []


def _heading_text(line: str) -> str | None:
    trimmed = line.lstrip()
    count = len(trimmed) - len(trimmed.lstrip("#"))
    if count == 0 or count > 6:
        return None
    rest = trimmed[count:]
    if not rest or not rest[0].isspace() or not rest.strip():
        return None
    return rest.strip()


def _chunks(body: str) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    heading = ""
    content: list[str] = []
    for line in body.splitlines():
        next_heading = _heading_text(line)
        if next_heading is not None:
            if content or heading:
                chunks.append((heading, "\n".join(content)))
            heading, content = next_heading, []
        else:
            content.append(line)
    if content or heading:
        chunks.append((heading, "\n".join(content)))
    return chunks


def _chunk_preview(heading: str, content: str) -> str:
    text = content.strip()[:CHUNK_PREVIEW_LEN].replace("\n", " ")
    return f"#{heading} — {text}" if heading else text


def score_body(body: str, terms: list[str]) -> tuple[int, str]:
    if not body.strip():
        return 0, ""
    best_score = 0
    best_preview = ""
    for heading, content in _chunks(body):
        score = score_text(heading, terms, HEADING_WEIGHT) + score_text(
            content, terms, CHUNK_BODY_WEIGHT
        )
        if score > best_score:
            best_score = score
            best_preview = _chunk_preview(heading, content)
    if best_score:
        return best_score, best_preview
    return 0, body.strip()[:FALLBACK_PREVIEW_LEN].replace("\n", " ")


__all__ = [
    "DEFAULT_LIMIT",
    "TextSearchResult",
    "field_weight",
    "query_terms",
    "score_body",
    "score_text",
    "search_text",
    "search_text_matching",
]
