"""Atomic runner configuration writes and timestamped backups."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_config(path: Path, text: str) -> None:
    previous = path.read_bytes() if path.exists() else None
    if previous is not None:
        backup = path.with_name(
            f"{path.name}.{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.bak"
        )
        atomic_write(backup, previous)
    atomic_write(path, text.encode("utf-8"))
    backups = sorted(
        path.parent.glob(f"{path.name}.*.bak"),
        key=lambda item: item.stat().st_mtime_ns,
        reverse=True,
    )
    for expired in backups[5:]:
        expired.unlink()
