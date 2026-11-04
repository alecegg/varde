"""Read-only friction search over an existing varde-learn store."""

from __future__ import annotations

from pathlib import Path

from varde_data.errors import DataError
from varde_data.friction import friction_store_exists, open_friction

from .types import SearchHit, SearchQuery, SourceResult

SOURCE = "friction"


class FrictionSearch:
    def __init__(self, store_dir: Path):
        self.store_dir = Path(store_dir)

    def source(self) -> str:
        return SOURCE

    def search(self, query: SearchQuery) -> SourceResult:
        if not friction_store_exists(self.store_dir):
            return SourceResult.unavailable(SOURCE, "no friction store")
        try:
            page = open_friction(self.store_dir).list_items(
                text=query.text, offset=0, limit=query.limit
            )
        except (DataError, OSError, ValueError) as error:
            return SourceResult.unavailable(SOURCE, str(error))
        return SourceResult.found(
            SOURCE,
            [
                SearchHit(
                    SOURCE, item.title, item.slug, f"{item.status} ({item.source})"
                )
                for item in page.items[: query.limit]
            ],
        )
