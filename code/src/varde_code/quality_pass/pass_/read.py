"""Read stored quality rows back as plain records.

The store exposes per-row ``get_*`` only, so these readers stream the tables
directly and verify each row's digest with the store's bare-hex blake2b scheme.
A reader never creates or writes the store.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from varde_code.quality_pass.facts import normalize_record
from varde_code.quality_pass.store import quality_store_path

_DIGEST_SIZE = 32


def read_facts(root: str | Path) -> Iterator[dict]:
    """Yield stored facts records by path, normalized to facts-2."""
    for value in _read_layer(root, "facts"):
        yield normalize_record(value)


def read_measures(root: str | Path) -> Iterator[dict]:
    """Yield stored L3 measures records by path."""
    yield from _read_layer(root, "measures")


def _read_layer(root: str | Path, layer: str) -> Iterator[dict]:
    path = _store_file(root)
    if not path.is_file():
        return
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            f"SELECT path, value, digest FROM {layer} ORDER BY path"  # noqa: S608 - Layer is selected from the internal layer constants.
        ).fetchall()
    except sqlite3.DatabaseError:
        rows = []
    finally:
        connection.close()
    for _path, value, digest in rows:
        if _digest(value) != digest:
            continue
        try:
            yield json.loads(value)
        except TypeError, json.JSONDecodeError:
            continue


def _digest(value: str) -> str:
    return hashlib.blake2b(value.encode("utf-8"), digest_size=_DIGEST_SIZE).hexdigest()


def _store_file(root: str | Path) -> Path:
    """Return the highest-numbered quality database beside the default one."""
    default = quality_store_path(root)
    best: tuple[int, Path] | None = None
    for candidate in default.parent.glob("quality-v*.sqlite"):
        match = re.fullmatch(r"quality-v(\d+)\.sqlite", candidate.name)
        if match and (best is None or int(match.group(1)) > best[0]):
            best = (int(match.group(1)), candidate)
    return best[1] if best is not None else default
