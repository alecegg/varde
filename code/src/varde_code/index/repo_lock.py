"""Per-repository advisory locks for index builds and prune operations."""

from __future__ import annotations

import errno
import os
import time
from pathlib import Path
from typing import Self

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX hosts
    fcntl = None

BASE_BACKOFF_SECONDS = 0.01
MAX_BACKOFF_SECONDS = 0.25


class RepoLock:
    """A held repository lock. Closing releases the kernel lock."""

    def __init__(self, file, path: Path) -> None:
        self._file = file
        self._path = path

    def close(self) -> None:
        if not self._file.closed:
            if fcntl is None:
                self._file.close()
                self._path.unlink(missing_ok=True)
            else:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
                self._file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def lock_path(db_path: Path) -> Path:
    return db_path.with_suffix(".db.lock")


def acquire(db_path: Path, timeout: float = 30.0) -> RepoLock:
    """Wait up to ``timeout`` seconds for an exclusive lock on the DB sibling."""
    path = lock_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file = path.open("a+")
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        try:
            if fcntl is None:
                # Exclusive creation is the best available non-POSIX fallback.
                file.close()
                file = path.open("x")
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            file.seek(0)
            file.truncate()
            file.write(str(os.getpid()))
            file.flush()
            return RepoLock(file, path)
        except FileExistsError:
            if fcntl is None:
                file = path.open("a+")
        except OSError as exc:
            if fcntl is None or exc.errno not in (errno.EACCES, errno.EAGAIN):
                file.close()
                raise OSError(f"locking {path}: {exc}") from exc
        if time.monotonic() >= deadline:
            file.close()
            raise TimeoutError(f"timed out waiting for repo lock at {path}")
        time.sleep(
            min(BASE_BACKOFF_SECONDS * (1 << min(attempt, 6)), MAX_BACKOFF_SECONDS)
        )
        attempt += 1


def probe(db_path: Path) -> tuple[bool, RepoLock | None]:
    """Probe without creating a lock file; return (held, guard)."""
    path = lock_path(db_path)
    try:
        file = path.open("rb")
    except OSError:
        return False, None
    if fcntl is None:
        file.close()
        try:
            guard = acquire(db_path, timeout=0)
            return False, guard
        except OSError, TimeoutError:
            return True, None
    try:
        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False, RepoLock(file, path)
    except OSError as exc:
        file.close()
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            return True, None
        return False, None
