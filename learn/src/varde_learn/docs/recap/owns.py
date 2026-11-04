"""Match changed paths against plan `owns` entries. Pure; no I/O.

An entry ending in `/`, or a bare path with no glob character, owns that exact
path and everything below it. Any other entry is a glob: `*` and `?` stay in
one path segment, `**` crosses segments (and may match none).
"""

import re
from functools import lru_cache

_GLOB_CHARS = frozenset("*?[")


def _is_glob(entry: str) -> bool:
    return any(c in _GLOB_CHARS for c in entry)


def _glob_regex(entry: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(entry):
        if entry.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif entry.startswith("**", i):
            out.append(".*")
            i += 2
        elif entry[i] == "*":
            out.append("[^/]*")
            i += 1
        elif entry[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(entry[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


@lru_cache(maxsize=512)
def _compiled(entry: str) -> re.Pattern[str]:
    return _glob_regex(entry)


def normalize(entry: str) -> str:
    return entry.strip().removeprefix("./")


def matches(entry: str, path: str) -> bool:
    entry = normalize(entry)
    if not entry:
        return False
    if entry.endswith("/") and not _is_glob(entry):
        return path.startswith(entry)
    if not _is_glob(entry):
        return path == entry or path.startswith(entry + "/")
    return bool(_compiled(entry).match(path))
