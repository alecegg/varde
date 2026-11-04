"""Factory and mode-aware access for the queue repository."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, cast

from varde_data.errors import WrongMode
from varde_data.queue_mode_lock import operation, require_role_queue_ready
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.repos.queue import QueueRepository
from varde_data.repos.slots import SlotRepository


class _ModeAwareQueue:
    """Run repository calls under the queue mode lock."""

    def __init__(self, root: Path, repository: QueueRepository) -> None:
        self._root = root
        self._repository = repository

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._repository, name)
        if not callable(attribute):
            return attribute

        def call(*args: Any, **kwargs: Any) -> Any:
            with operation(self._root) as mode:
                if mode != "sqlite":
                    raise WrongMode("queue repository requires SQLite store mode")
                return attribute(*args, **kwargs)

        return call


def open_queue(root: Path, backend_name: str = "sqlite") -> QueueRepository:
    """Open a queue repository for the working directory."""
    if backend_name == "memory":
        module = importlib.import_module("varde_data.backends.memory.queue")
        repository = module.MemoryQueue()
        return cast("QueueRepository", repository)
    if backend_name == "sqlite":
        require_role_queue_ready(root)
        module = importlib.import_module("varde_data.backends.sqlite.queue")
        database = root / QUEUE_DATABASE
        repository = cast("Any", module.SQLiteQueue(database))
    else:
        raise ValueError(f"unknown queue backend: {backend_name}")
    return cast("QueueRepository", _ModeAwareQueue(root, repository))


class _ModeAwareSlots:
    """Run slot repository calls under the queue mode lock."""

    def __init__(self, root: Path, repository: SlotRepository) -> None:
        self._root = root
        self._repository = repository

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._repository, name)
        if not callable(attribute):
            return attribute

        def call(*args: Any, **kwargs: Any) -> Any:
            with operation(self._root) as mode:
                if mode != "sqlite":
                    raise WrongMode("slot repository requires SQLite store mode")
                return attribute(*args, **kwargs)

        return call


def open_slots(root: Path, backend_name: str = "sqlite") -> SlotRepository:
    """Open the store-only slot repository in the queue database."""
    if backend_name != "sqlite":
        raise WrongMode("slot repository requires SQLite store mode")
    require_role_queue_ready(root)
    module = importlib.import_module("varde_data.backends.sqlite.slots")
    database = root / QUEUE_DATABASE
    repository = cast("Any", module.SQLiteSlots(database, root))
    return cast("SlotRepository", _ModeAwareSlots(root, repository))


__all__ = ["open_queue", "open_slots"]
