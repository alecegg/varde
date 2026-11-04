"""One search library over the entry index (SQLite FTS5 with a term-scorer fallback)."""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from varde_learn.knowledge.crud.search import (
    CHUNK_BODY_WEIGHT,
    SLUG_WEIGHT,
    field_weight,
    query_terms,
    score_body,
    score_text,
)
from varde_learn.memory import ops, searchindex
from varde_learn.memory.entry import Entry
from varde_learn.memory.expiry import is_past

DEFAULT_LIMIT = 20
SCORE_SCALE = 1_000_000
_notice_printed = False


@dataclass(frozen=True)
class Hit:
    slug: str
    path: Path
    type: str
    score: int
    preview: str
    rank: float = 0.0


@dataclass(frozen=True)
class SearchOptions:
    filters: tuple[tuple[str, str], ...] = ()
    topic: str = ""
    scopes: tuple[str, ...] = ()
    include_expired: bool = False
    limit: int | None = DEFAULT_LIMIT
    today: date | None = None


def search(
    source: searchindex.Source,
    text: str,
    options: SearchOptions = SearchOptions(),  # noqa: B008 - frozen dataclass
    index_file: Path | None = None,
) -> list[Hit]:
    """Ranked hits for `text`. An in-memory index is used when no file is given."""
    terms = query_terms(text)
    if not terms:
        return []
    with closing(searchindex.connect(source, index_file)) as conn:
        rows = _candidate_rows(conn, terms, source)
    return _rank_hits(rows, _entries_by_path(source, options), options, terms)


def search_substring(
    source: searchindex.Source,
    text: str,
    options: SearchOptions = SearchOptions(),  # noqa: B008 - frozen dataclass
) -> list[Hit]:
    """The old knowledge matching: terms match anywhere inside a field or the slug.

    Scans the entries directly, so it needs no index and no FTS5. Prefix search
    (`search`) is the default; this keeps the substring behavior reachable.
    """
    terms = query_terms(text)
    if not terms:
        return []
    rows = _substring_rows(source, terms)
    return _rank_hits(rows, _entries_by_path(source, options), options, terms)


def _rank_hits(
    rows: list[dict],
    entries: dict[str, Entry],
    options: SearchOptions,
    terms: list[str],
) -> list[Hit]:
    today = options.today or date.today()
    hits = [
        hit
        for row in rows
        if (hit := _hit(row, entries, options, today, terms)) is not None
    ]
    hits.sort(key=lambda hit: (hit.rank, hit.slug))
    return hits if options.limit is None else hits[: max(0, options.limit)]


def _candidate_rows(
    conn: sqlite3.Connection, terms: list[str], source: searchindex.Source
) -> list[dict]:
    conn.row_factory = sqlite3.Row
    if searchindex.has_fts(conn):
        return _fts_rows(conn, terms)
    _notice("FTS5 is unavailable; using the term scorer")
    return _substring_rows(source, terms)


def _fts_rows(conn: sqlite3.Connection, terms: list[str]) -> list[dict]:
    weights = ", ".join(str(_column_weight(c)) for c in searchindex.FTS_COLUMNS)
    match = " OR ".join(f'"{term}"*' for term in terms)
    rank = f"bm25(entries_fts, {weights})"  # integer constants only
    sql = (
        "SELECT e.*, f.body AS body, " + rank + " AS rank "
        "FROM entries_fts f JOIN entries e ON e.rowid = f.rowid "
        "WHERE entries_fts MATCH ?"
    )
    rows = conn.execute(sql, (match,)).fetchall()
    return [dict(row) | {"score": _scale(row["rank"])} for row in rows]


def _substring_rows(source: searchindex.Source, terms: list[str]) -> list[dict]:
    loaded, _ = source.load()
    found: list[dict] = []
    for entry in loaded:
        path = source.path_of(entry)
        score = _field_score(entry, terms)
        body_score, _ = score_body(entry.text, terms)
        if score + body_score > 0:
            found.append(_row_of(entry, path, score + body_score))
    return found


def _field_score(entry: Entry, terms: list[str]) -> int:
    fields = {
        "title": entry.title,
        "aliases": " ".join(entry.aliases),
        "tags": " ".join(entry.tags),
        "description": entry.description,
        "topic": entry.topic,
        "extra": searchindex.flatten_values(entry.extra),
    }
    score = score_text(searchindex.slug_text(entry), terms, SLUG_WEIGHT)
    return score + sum(
        score_text(text, terms, field_weight(name)) for name, text in fields.items()
    )


def _row_of(entry: Entry, path: Path, score: int) -> dict:
    return {
        "id": entry.id,
        "path": str(path),
        "scope": entry.scope,
        "topic": entry.topic,
        "type": entry.type,
        "valid_until": entry.valid_until,
        "body": entry.text,
        "score": score,
        "rank": -score,
    }


def _hit(
    row: dict,
    entries: dict[str, Entry],
    options: SearchOptions,
    today: date,
    terms: list[str],
) -> Hit | None:
    if options.scopes and row["scope"] not in options.scopes:
        return None
    if options.topic and row["topic"] != options.topic:
        return None
    if not options.include_expired and is_past(row["valid_until"], today):
        return None
    if options.filters and not _passes_filters(row, entries, options.filters):
        return None
    _, preview = score_body(row["body"], terms)
    return Hit(
        row["id"], Path(row["path"]), row["type"], row["score"], preview, row["rank"]
    )


def _passes_filters(
    row: dict, entries: dict[str, Entry], filters: tuple[tuple[str, str], ...]
) -> bool:
    entry = entries.get(row["path"])
    return entry is not None and bool(ops.filter_entries([entry], list(filters)))


def _entries_by_path(
    source: searchindex.Source, options: SearchOptions
) -> dict[str, Entry]:
    if not options.filters:
        return {}
    loaded, _ = source.load()
    return {str(source.path_of(entry)): entry for entry in loaded}


def _column_weight(column: str) -> int:
    if column == "slug":
        return SLUG_WEIGHT
    return CHUNK_BODY_WEIGHT if column == "body" else field_weight(column)


def _scale(rank: float) -> int:
    """bm25 is lower-is-better and tiny on small corpora; show it as a positive integer.

    Ordering uses the float rank, so the rounding never creates ties.
    """
    return max(1, round(-rank * SCORE_SCALE))


def _notice(message: str) -> None:
    global _notice_printed  # noqa: PLW0603 - print the fallback notice once
    if not _notice_printed:
        _notice_printed = True
        print(f"notice: {message}", file=sys.stderr)
