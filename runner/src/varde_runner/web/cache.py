"""Small cache helpers for dashboard data that changes on disk."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_data.cache import CachedData, UnstableDataError
from varde_data.config import load_data_config
from varde_data.errors import Invalid, Locked
from varde_data.messages import open_messages
from varde_data.open import open_data
from varde_data.repos.messages import MessageRepository

from varde_runner.messages import message_dict


@dataclass(frozen=True)
class InboxSnapshot:
    messages: list[dict[str, Any]]
    acknowledged_ids: set[str]
    concluded_addresses: set[str]


def watched_files_signature(
    roots: tuple[Path, ...],
    message_repository: MessageRepository | None = None,
) -> tuple[tuple[Any, ...], ...]:
    """Return path and stat data for files that can change a dashboard snapshot."""
    paths = set()
    for root in roots:
        if root.is_file():
            if not _is_inbox_sqlite_sidecar(root):
                paths.add(root)
        elif root.is_dir():
            paths.update(
                path
                for path in root.rglob("*")
                if path.is_file() and not _is_inbox_sqlite_sidecar(path)
            )
    signature = []
    for path in sorted(paths):
        try:
            stat = path.stat()
        except OSError:
            continue
        signature.append(
            (str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino, stat.st_ctime_ns)
        )
    signature.extend(_message_version_signatures(paths, message_repository))
    return tuple(signature)


def _message_version_signatures(
    paths: set[Path], message_repository: MessageRepository | None
) -> list[tuple[Any, ...]]:
    signatures = []
    for database in sorted(paths):
        inbox = database.parent
        if (
            database.name != "messages.sqlite3"
            or inbox.name != "inbox"
            or inbox.parent.name != ".cache"
        ):
            continue
        working = inbox.parent.parent
        try:
            repository = message_repository
            if repository is None:
                repository = open_messages(working, "sqlite", busy_timeout=0.05)
            signatures.append(
                (str(database), "message-version", repository.version().value)
            )
        except sqlite3.Error, OSError, Locked, Invalid:
            continue
    return signatures


def _is_inbox_sqlite_sidecar(path: Path) -> bool:
    is_sidecar = path.name.endswith(("-wal", "-shm"))
    in_inbox = any(
        parent.name == "inbox" and parent.parent.name == ".cache"
        for parent in path.parents
    )
    return is_sidecar and in_inbox


class InboxStoreCache:
    """Read inbox data through the shared message repository."""

    def __init__(self, working_dir: Path) -> None:
        self.repository = open_data(working_dir, load_data_config()).messages
        self._lock = threading.Lock()
        self._cache = CachedData(self._load, self.repository.version)

    def _load(self) -> InboxSnapshot:
        messages = [message_dict(row) for row in self.repository.read_all().records]
        status = self.repository.status()
        return InboxSnapshot(
            messages,
            set(status.acked),
            self.repository.concluded_addresses(),
        )

    def read(self) -> InboxSnapshot:
        with self._lock:
            try:
                return self._cache.get()
            except UnstableDataError:
                return InboxSnapshot([], set(), set())

    def read_messages(self) -> list[dict[str, Any]]:
        return self.read().messages
