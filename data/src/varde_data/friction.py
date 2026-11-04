"""Factory for selecting a friction repository backend."""

import importlib
from pathlib import Path
from typing import cast

from varde_data.learn_registry import load_sqlite_backend, resolve_backend
from varde_data.learn_store_mode import DB_NAME
from varde_data.repos.friction import FrictionRepository


def friction_store_exists(root: Path) -> bool:
    """Return whether a friction store has a log, legacy index or sqlite file."""
    names = ("friction.jsonl", "learn.db", DB_NAME)
    return any((root / name).is_file() for name in names)


def open_friction(root: Path, backend_name: str | None = None) -> FrictionRepository:
    """Open a friction repository without importing unused backends.

    Without a backend name, the learn root's store marker selects the backend.
    """
    backend_name = resolve_backend(root, "friction", backend_name)
    if backend_name == "memory":
        from varde_data.testing import MemoryFriction

        return MemoryFriction(root)
    if backend_name == "files":
        module = importlib.import_module("varde_data.backends.files.friction")
        return cast("FrictionRepository", module.FilesFriction(root))
    if backend_name == "sqlite":
        return cast("FrictionRepository", load_sqlite_backend("friction")(root))
    raise ValueError(f"unknown friction backend: {backend_name}")
