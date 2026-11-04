"""Foundational-file leaderboard shared by nav_map and query modes."""

from __future__ import annotations

import sqlite3
from typing import Any

from .noise_filter import is_frontend_asset_path, is_generated_or_vendored_path
from .symbols_section import is_accessor

_BOILERPLATE = {
    "equals",
    "hashcode",
    "tostring",
    "compareto",
    "clone",
    "copy",
    "builder",
    "of",
    "valueof",
    "with",
    "deconstruct",
}


def leaderboard(
    conn: sqlite3.Connection, limit: int | None = None
) -> list[dict[str, Any]]:
    dependents = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT to_file_id, COUNT(DISTINCT from_file_id) FROM resolved_edges "
            "WHERE resolved=1 AND to_file_id IS NOT NULL "
            "AND from_file_id != to_file_id GROUP BY to_file_id"
        )
    }
    methods: dict[int, bool] = {}
    for fid, name in conn.execute("SELECT file_id,name FROM entities WHERE kind=0"):
        methods[fid] = methods.get(fid, True) and (
            is_accessor(name) or name.lower() in _BOILERPLATE
        )
    rows = []
    for fid, path, fan_in in conn.execute(
        "SELECT id,path,fan_in FROM files WHERE fan_in>0 AND is_test_path=0"
    ):
        if is_generated_or_vendored_path(path) or is_frontend_asset_path(path):
            continue
        rows.append((methods.get(fid, False), dependents.get(fid, 0), fan_in, path))
    rows.sort(key=lambda item: (item[0], -item[1], -item[2], item[3]))
    if limit is not None:
        rows = rows[:limit]
    return [
        {
            "file": path,
            "count": fan_in,
            "dependents": deps,
            "why": (
                f"depended on by {deps} other file{'s' if deps != 1 else ''} "
                "in the repo"
                if deps == fan_in
                else f"depended on by {deps} other file{'s' if deps != 1 else ''} "
                f"({fan_in} references total) in the repo"
            ),
        }
        for _data, deps, fan_in, path in rows
    ]
