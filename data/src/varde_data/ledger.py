"""Factory for selecting a session-ledger backend."""

import importlib
from pathlib import Path
from typing import cast

from varde_data.learn_registry import load_sqlite_backend, resolve_backend
from varde_data.repos.ledger import LedgerRepository


def open_ledger(root: Path, backend_name: str | None = None) -> LedgerRepository:
    """Open the ledger; without a backend name the learn root's marker decides."""
    backend_name = resolve_backend(root, "ledger", backend_name)
    if backend_name == "memory":
        from varde_data.testing import MemoryLedger

        return MemoryLedger(root)
    if backend_name == "files":
        module = importlib.import_module("varde_data.backends.files.ledger")
        return cast("LedgerRepository", module.FilesLedger(root))
    if backend_name == "sqlite":
        return cast("LedgerRepository", load_sqlite_backend("ledger")(root))
    raise ValueError(f"unknown ledger backend: {backend_name}")
