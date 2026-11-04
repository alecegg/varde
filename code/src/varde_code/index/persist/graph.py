"""SQLite implementation of the Python-format graph cache seam."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from varde_code.graph_model import Graph


class SqliteGraphCache:
    """Read and write the single-row graph cache using ``Graph.to_dict`` JSON."""

    def read(self, db_path: Path, rev: int) -> Graph | None:
        try:
            with sqlite3.connect(db_path) as connection:
                row = connection.execute(
                    "SELECT blob, rev FROM graph_cache WHERE id = 1"
                ).fetchone()
        except sqlite3.Error:
            return None
        if row is None or row[1] != rev:
            return None
        try:
            value = json.loads(bytes(row[0]))
            if not isinstance(value, dict):
                return None
            return Graph.from_dict(value)
        except UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError:
            return None

    def write(self, db_path: Path, graph: Graph, rev: int) -> None:
        blob = json.dumps(
            graph.to_dict(), separators=(",", ":"), sort_keys=True
        ).encode()
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "INSERT INTO graph_cache(id, blob, rev) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET blob=excluded.blob, rev=excluded.rev",
                (blob, rev),
            )
