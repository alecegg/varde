"""Code search over an existing varde-code index."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from varde_code.query import run_mode

from .types import SearchHit, SearchQuery, SourceResult

SOURCE = "code"


class CodeSearch:
    """Search a prebuilt code index without building or changing it."""

    def __init__(self, repo_root: Path, db_path: Path):
        self.repo_root = Path(repo_root)
        self.db_path = Path(db_path)

    def source(self) -> str:
        return SOURCE

    def search(self, query: SearchQuery) -> SourceResult:
        payload = {
            "repoRoot": str(self.repo_root),
            "dbPath": str(self.db_path),
            "query": query.text,
            "fullResults": True,
        }
        return code_hits_from_envelope(
            run_mode("context_pack", json.dumps(payload, separators=(",", ":"))),
            query.limit,
        )


def code_hits_from_envelope(envelope: str, limit: int) -> SourceResult:
    """Map a context_pack envelope to search hits."""
    try:
        value: Any = json.loads(envelope)
    except ValueError, TypeError:
        return SourceResult.unavailable(SOURCE, "unreadable code query result")
    if not isinstance(value, dict):
        return SourceResult.unavailable(SOURCE, "unreadable code query result")
    if value.get("ok") is not True:
        data = value.get("data")
        error = data.get("error") if isinstance(data, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        code = code if isinstance(code, str) else "error"
        if code == "not_found":
            return SourceResult.found(SOURCE, ())
        return SourceResult.unavailable(SOURCE, code)

    data = value.get("data")
    if not isinstance(data, dict):
        return SourceResult.found(SOURCE, ())
    hits = [*_file_hits(data.get("files")), *_symbol_hits(data.get("symbols"))]
    return SourceResult.found(SOURCE, hits[:limit])


def _file_hits(files: object) -> list[SearchHit]:
    if not isinstance(files, list):
        return []
    hits = []
    for file in files:
        if not isinstance(file, dict) or not isinstance(file.get("path"), str):
            continue
        path = file["path"]
        relevance = file.get("relevance")
        hits.append(
            SearchHit(
                SOURCE, path, path, relevance if isinstance(relevance, str) else ""
            )
        )
    return hits


def _symbol_hits(symbols: object) -> list[SearchHit]:
    if not isinstance(symbols, list):
        return []
    hits = []
    for symbol in symbols:
        if not isinstance(symbol, dict):
            continue
        name, path = symbol.get("name"), symbol.get("filePath")
        if not isinstance(name, str) or not isinstance(path, str):
            continue
        span = symbol.get("span")
        line = span.get("start_line", 0) if isinstance(span, dict) else 0
        line = line if isinstance(line, int) and line >= 0 else 0
        kind = symbol.get("kind")
        hits.append(
            SearchHit(
                SOURCE, name, f"{path}:{line}", kind if isinstance(kind, str) else ""
            )
        )
    return hits
