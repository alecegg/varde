"""Language extraction table discovery and shared dispatch."""

from __future__ import annotations

from functools import lru_cache

from varde_code.parse import language_name

from .base import LanguageTables, VisitRule, discover


@lru_cache(maxsize=1)
def language_tables() -> dict[str, LanguageTables]:
    return discover()


def tables_for(language: str) -> LanguageTables:
    canonical = language_name(language)
    return language_tables().get(canonical, LanguageTables())


__all__ = ["LanguageTables", "VisitRule", "language_tables", "tables_for"]
