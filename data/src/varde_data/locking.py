"""Locking and durable file helpers shared by data stores.

Later domain steps must reuse their established lock paths: friction locks
``friction.jsonl`` itself; inbox uses ``.<reader>.lock``; relay uses
``relay/.lock``; binding locks the per-address directory; queue order uses
``.queue-order.json.lock``. Stores without an established lock use a sibling
``.lock`` file.
"""

from __future__ import annotations

import errno
import fcntl
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from varde_data.errors import Locked


@contextmanager
def file_lock(path: Path, *, timeout: float) -> Iterator[None]:
    """Hold an advisory exclusive lock, raising ``Locked`` when timed out."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    raise Locked from error
                time.sleep(min(0.01, max(0, deadline - time.monotonic())))
        yield
    finally:
        os.close(descriptor)


@contextmanager
def shared_file_lock(path: Path, *, timeout: float) -> Iterator[None]:
    """Hold a shared lock, raising ``Locked`` when the wait exceeds timeout."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    raise Locked(
                        "message store mode is busy; retry the operation"
                    ) from error
                time.sleep(min(0.01, max(0, deadline - time.monotonic())))
        yield
    finally:
        os.close(descriptor)


@contextmanager
def blocking_file_lock(path: Path, *, mode: int = 0o666) -> Iterator[None]:
    """Hold an advisory exclusive lock, blocking until it is available."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, mode)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def atomic_write(path: Path, data: bytes, *, mode: int) -> None:
    """Atomically replace a file and sync both its contents and directory."""
    _atomic_write(path, data, mode=mode, sync=True)


def atomic_write_unsynced(path: Path, data: bytes, *, mode: int) -> None:
    """Atomically replace a derived file without syncing to disk."""
    _atomic_write(path, data, mode=mode, sync=False)


def _atomic_write(path: Path, data: bytes, *, mode: int, sync: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
        if sync:
            os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise
    os.close(descriptor)
    try:
        os.replace(temporary, path)
        if sync:
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _has_torn_tail(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open("rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        if not size:
            return False
        stream.seek(-1, os.SEEK_END)
        return stream.read(1) != b"\n"


def append_line(path: Path, line: bytes, *, lock_path: Path) -> None:
    """Append one newline-terminated record while holding its designated lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(lock_path, timeout=30):
        prefix = b"\n" if _has_torn_tail(path) else b""
        payload = prefix + line.rstrip(b"\n") + b"\n"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            written = os.write(descriptor, payload)
            if written != len(payload):
                raise OSError(errno.EIO, os.strerror(errno.EIO))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def read_complete_lines(path: Path) -> list[bytes]:
    """Read newline-terminated records, ignoring any torn final record."""
    try:
        contents = path.read_bytes()
    except FileNotFoundError:
        return []
    if not contents.endswith(b"\n"):
        contents = contents[: contents.rfind(b"\n") + 1]
    return contents[:-1].split(b"\n") if contents else []


def remove_stale_temps(directory: Path, older_than: float) -> int:
    """Remove sibling atomic-write temps older than ``older_than`` seconds."""
    cutoff = time.time() - older_than
    removed = 0
    for path in directory.glob(".*.*.tmp"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except FileNotFoundError:
            continue
    return removed
