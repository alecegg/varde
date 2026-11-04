"""Opaque version and cursor tokens for shared data readers."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Version:
    """An equality-only token describing a snapshot of data."""

    value: object
    _mtimes_ns: tuple[int, ...] = field(
        default=(), repr=False, compare=False, hash=False
    )

    def is_racy_at(self, timestamp_ns: int) -> bool:
        """Whether any source file was modified within two seconds of a load."""
        return any(
            abs(mtime_ns - timestamp_ns) <= 2_000_000_000
            for mtime_ns in self._mtimes_ns
        )


@dataclass(frozen=True, order=True)
class Cursor:
    """An opaque, ordered position in a data stream."""

    value: str


def files_version(
    paths: Iterable[str | os.PathLike[str]],
    *,
    file_set_root: str | os.PathLike[str] | None = None,
) -> Version:
    """Build a token from file metadata and, optionally, a recursive file set."""
    file_paths = sorted({Path(path) for path in paths}, key=os.fspath)
    stats: list[tuple[str, int, int, int, int] | tuple[str, None]] = []
    mtimes: list[int] = []
    for path in file_paths:
        try:
            info = path.stat()
        except FileNotFoundError:
            stats.append((os.fspath(path), None))
            continue
        stats.append(
            (
                os.fspath(path),
                info.st_mtime_ns,
                info.st_ctime_ns,
                info.st_size,
                info.st_ino,
            )
        )
        mtimes.append(info.st_mtime_ns)

    names: tuple[str, ...] = ()
    if file_set_root is not None:
        root = Path(file_set_root)
        if root.exists():
            names = tuple(
                sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            )
    return Version((tuple(stats), names), tuple(mtimes))
