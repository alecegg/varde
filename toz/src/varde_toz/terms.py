"""Distinctive vocabulary extraction from stored chunks."""

from __future__ import annotations

import math
import re
from collections import Counter

_STOP = {
    "the",
    "and",
    "for",
    "are",
    "but",
    "not",
    "you",
    "all",
    "any",
    "can",
    "had",
    "her",
    "was",
    "one",
    "our",
    "out",
    "has",
    "have",
    "this",
    "that",
    "with",
    "from",
    "they",
    "will",
    "would",
    "there",
    "their",
    "what",
    "about",
    "which",
    "when",
    "make",
    "like",
    "time",
    "just",
    "into",
    "than",
    "them",
    "then",
    "these",
    "some",
    "could",
    "other",
    "also",
    "more",
    "most",
    "such",
    "only",
    "over",
    "very",
    "your",
    "each",
    "does",
    "done",
    "true",
    "false",
    "null",
    "none",
    "self",
    "let",
    "mut",
    "pub",
    "use",
    "const",
    "static",
    "return",
    "else",
    "while",
    "loop",
    "match",
    "impl",
    "struct",
    "enum",
    "type",
    "where",
    "async",
    "await",
    "move",
    "ref",
    "dyn",
    "string",
    "str",
    "int",
    "bool",
    "vec",
    "option",
    "result",
    "error",
    "warning",
    "info",
    "debug",
    "trace",
    "line",
    "lines",
    "file",
    "files",
    "new",
    "old",
    "get",
    "set",
    "value",
    "values",
    "name",
    "names",
    "key",
    "keys",
    "data",
    "item",
    "items",
    "list",
    "test",
    "tests",
    "running",
    "passed",
    "failed",
    "ignored",
    "measured",
    "filtered",
    "finished",
    "import",
    "export",
    "default",
    "function",
    "class",
    "def",
    "var",
    "end",
    "begin",
    "print",
    "println",
    "format",
    "todo",
    "fixme",
    "note",
    "see",
    "via",
    "per",
    "etc",
}


def distinctive(chunks: list[str], limit: int = 8) -> list[str]:
    if len(chunks) < 3:
        return []
    df: Counter[str] = Counter()
    for body in chunks:
        found = {word.strip("-") for word in re.findall(r"[\w-]+", body, re.UNICODE)}
        df.update(
            word
            for word in found
            if 3 <= len(word.encode()) <= 40
            and not word.isdigit()
            and word.lower() not in _STOP
        )
    max_docs = max(3, math.ceil(len(chunks) * 0.4))
    scored = []
    for word, count in df.items():
        if 2 <= count <= max_docs:
            score = math.log(len(chunks) / count) + min(len(word.encode()) / 20, 0.5)
            score += (
                1.5
                if "_" in word or "-" in word
                else 0.8
                if len(word.encode()) >= 12
                or (any(c.isupper() for c in word) and any(c.islower() for c in word))
                else 0
            )
            scored.append((word, score))
    result = []
    seen = set()
    for word, _ in sorted(scored, key=lambda pair: (-pair[1], pair[0])):
        if word.lower() not in seen:
            result.append(word)
            seen.add(word.lower())
        if len(result) >= limit:
            break
    return result
