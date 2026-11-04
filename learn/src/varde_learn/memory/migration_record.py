"""Migration records: `<root>/.migrations/knowledge-<hash>.json` (pure file helpers)."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

MIGRATIONS_DIR = ".migrations"


def record_path(root: Path, bundle: Path) -> Path:
    digest = hashlib.sha256(str(bundle.resolve()).encode()).hexdigest()[:12]
    return root / MIGRATIONS_DIR / f"knowledge-{digest}.json"


def read_record(root: Path, bundle: Path) -> dict | None:
    """The record for a bundle, or None when absent or unreadable."""
    try:
        data = json.loads(record_path(root, bundle).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    return data if isinstance(data, dict) else None


def write_record(root: Path, bundle: Path, created: dict[str, str]) -> Path:
    """Write the record atomically; `created` maps each path to its `occ.version`."""
    path = record_path(root, bundle)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"bundle": str(bundle.resolve()), "created": created}
    text = json.dumps(body, indent=2, sort_keys=True) + "\n"
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def remove_record(root: Path, bundle: Path) -> bool:
    """Delete the record; return whether one existed."""
    path = record_path(root, bundle)
    if not path.exists():
        return False
    path.unlink()
    return True
