"""Search concepts in an existing knowledge bundle."""

from __future__ import annotations

from pathlib import Path

from varde_learn.knowledge.crud.search import search_text_matching

from .types import SearchHit, SearchQuery, SourceResult

SOURCE = "knowledge"


class KnowledgeSearch:
    def __init__(self, bundle: Path):
        self.bundle = Path(bundle)

    def source(self) -> str:
        return SOURCE

    def search(self, query: SearchQuery) -> SourceResult:
        if not self.bundle.is_dir():
            return SourceResult.unavailable(SOURCE, "knowledge bundle not found")
        try:
            results = search_text_matching([self.bundle], query.text, [], query.limit)
        except (OSError, ValueError) as error:
            return SourceResult.unavailable(SOURCE, str(error))
        return SourceResult.found(
            SOURCE,
            [
                SearchHit(
                    SOURCE, result.slug, result.slug, result.preview, result.score
                )
                for result in results
            ],
        )
