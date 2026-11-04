"""Optional FTS5 lexical index for persisted entities."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from varde_code.index.persist.entities import FileIds

MAX_BODY_CHARS = 2000
_INDEXED_KINDS = {0, 1}  # functions/methods and classes
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "what",
    "where",
    "with",
}


def lexical_search(
    conn: sqlite3.Connection, query: str, limit: int
) -> list[tuple[int, float]]:
    """Return matching entity IDs ordered by FTS5 BM25 rank."""
    if not lexical_available(conn) or not query.strip() or limit <= 0:
        return []
    terms = [
        term
        for term in re.findall(r"[\w]+", query, flags=re.UNICODE)
        if len(term) >= 3 and term.casefold() not in _STOPWORDS
    ]
    if not terms:
        return []
    expression = " OR ".join(f'"{term}"' for term in terms)
    try:
        return [
            (int(entity_id), float(score))
            for entity_id, score in conn.execute(
                "SELECT rowid, bm25(lexical) FROM lexical "
                "WHERE lexical MATCH ? ORDER BY bm25(lexical) LIMIT ?",
                (expression, limit),
            )
        ]
    except sqlite3.OperationalError:
        return []


def index_outputs(
    conn: sqlite3.Connection, outputs, file_ids: FileIds, entity_ids: list[int]
) -> None:
    """Index selected extracted entities, reading each source file once."""
    if not lexical_available(conn):
        return
    rows = []
    entity_offset = 0
    for output in outputs:
        indexed_entities = [
            entity
            for entity in output.entities
            if entity.kind.as_i64() in _INDEXED_KINDS
        ]
        sources = {}
        for file_index, path in enumerate(output.files) if indexed_entities else ():
            try:
                sources[file_index] = Path(path).read_bytes()
            except OSError:
                sources[file_index] = b""
        for entity in output.entities:
            entity_id = entity_ids[entity_offset]
            entity_offset += 1
            if entity_id < 0 or entity.kind.as_i64() not in _INDEXED_KINDS:
                continue
            raw = sources.get(entity.file_id, b"")[
                entity.span.start_byte : entity.span.end_byte
            ][: MAX_BODY_CHARS * 4]
            body = raw.decode("utf-8", errors="replace")[:MAX_BODY_CHARS]
            rows.append((entity_id, entity.name, _leading_documentation(body), body))
    conn.executemany("INSERT INTO lexical(rowid,name,doc,body) VALUES (?,?,?,?)", rows)


def _leading_documentation(body: str) -> str:
    docstring = re.search(r"(?:\"\"\"|''')(.*?)(?:\"\"\"|''')", body, re.DOTALL)
    if docstring:
        return docstring.group(1)
    lines = body.splitlines()
    comments = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "//", "/*", "*", '"""', "'''")):
            comments.append(stripped)
            if stripped.endswith(('"""', "'''", "*/")) and len(comments) > 1:
                break
            continue
        break
    return " ".join(comments)


def lexical_available(conn: sqlite3.Connection) -> bool:
    cached = (
        conn.execute(
            "SELECT available FROM temp.varde_lexical_probe LIMIT 1"
        ).fetchone()
        if _probe_table_exists(conn)
        else None
    )
    if cached is not None:
        return bool(cached[0])
    available = (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lexical'"
        ).fetchone()
        is not None
    )
    conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS varde_lexical_probe (available INTEGER)"
    )
    conn.execute("DELETE FROM temp.varde_lexical_probe")
    conn.execute("INSERT INTO temp.varde_lexical_probe VALUES (?)", (int(available),))
    return available


def _probe_table_exists(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_temp_master WHERE type='table' AND name='varde_lexical_probe'"
        ).fetchone()
        is not None
    )
