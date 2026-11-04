"""Cross-file symbol caller leaderboard used by nav_map."""

from __future__ import annotations

import sqlite3
from typing import Any

from .noise_filter import is_frontend_asset_path, is_generated_or_vendored_path

_LOW = {
    "new",
    "push",
    "pop",
    "size",
    "len",
    "length",
    "begin",
    "end",
    "clone",
    "merge",
    "dig",
    "unwrap",
    "default",
    "hash",
    "into",
    "from",
    "as_str",
    "as_ref",
    "as_mut",
    "to_string",
    "tostring",
    "configureawait",
    "true",
    "false",
    "none",
    "null",
    "notnull",
    "nil",
}


def is_accessor(name: str) -> bool:
    for prefix in ("get", "set", "is", "has"):
        rest = name[len(prefix) :] if name.startswith(prefix) else None
        if rest is not None and (
            not rest or rest[0] == "_" or rest[0].isascii() and rest[0].isupper()
        ):
            return True
    return False


def leaderboard(
    conn: sqlite3.Connection, entrypoint_ids: set[int], limit: int | None = None
) -> list[dict[str, Any]]:
    entries = []
    rows = conn.execute("""SELECT e.id,f.path,e.name,e.owner_type,
        COUNT(DISTINCT re.from_file_id) breadth,COUNT(re.id) total
        FROM entities e JOIN files f ON f.id=e.file_id
        JOIN resolved_edges re ON re.to_entity_id=e.id AND re.resolved=1
            AND re.kind=0 AND re.from_file_id!=e.file_id
        WHERE e.kind IN (0,1) AND f.is_test_path=0 GROUP BY e.id
        HAVING COUNT(DISTINCT re.from_file_id)>0
        ORDER BY breadth DESC,total DESC,f.path,e.name""")
    for eid, path, name, owner, breadth, _total in rows:
        if (
            eid in entrypoint_ids
            or is_generated_or_vendored_path(path)
            or is_frontend_asset_path(path)
            or is_accessor(name)
            or name.lower() in _LOW
        ):
            continue
        entries.append(
            {"file": path, "symbol": name, "owner": owner, "callers": breadth}
        )
        if limit is not None and len(entries) >= limit:
            break
    return entries
