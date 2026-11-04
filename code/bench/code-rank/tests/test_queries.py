from __future__ import annotations

import json
import re
from pathlib import Path

DATA = Path(__file__).parents[1] / "data/queries.json"


def tokens(value: str) -> set[str]:
    return {
        token.lower() for token in re.findall(r"[A-Za-z0-9]+", value) if len(token) >= 3
    }


def test_queries_are_content_independent_and_sources_are_balanced() -> None:
    queries = json.loads(DATA.read_text())
    assert len(queries) >= 90
    assert sum(query["source"] == "commit" for query in queries) >= 50
    assert {query["repo"] for query in queries} == {"varde", "openspec", "agent-deck"}
    assert {query["source"] for query in queries} <= {"commit", "handwritten"}
    for query in queries:
        path_tokens = set().union(*(tokens(path) for path in query["relevant_files"]))
        assert not (tokens(query["query"]) & path_tokens), query["id"]
        if query["source"] == "commit":
            assert query.get("commit")
