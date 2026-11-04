"""Plain data shared by Varde modules."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SearchQuery:
    text: str
    limit: int


@dataclass(frozen=True)
class SearchHit:
    source: str
    title: str
    location: str
    snippet: str
    score: int | None = None


@dataclass(frozen=True)
class SourceResult:
    """Result from one search source; either hits or an unavailable reason."""

    source: str
    hits: tuple[SearchHit, ...] | None = None
    reason: str | None = None

    @classmethod
    def found(
        cls, source: str, hits: list[SearchHit] | tuple[SearchHit, ...]
    ) -> SourceResult:
        return cls(source=source, hits=tuple(hits))

    @classmethod
    def unavailable(cls, source: str, reason: str) -> SourceResult:
        return cls(source=source, reason=reason)


class SearchSource(Protocol):
    def source(self) -> str: ...

    def search(self, query: SearchQuery) -> SourceResult: ...
