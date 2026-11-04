"""Factory for selecting a CLI-call log backend."""

import importlib
from pathlib import Path
from typing import cast

from varde_data.learn_registry import load_sqlite_backend, resolve_backend
from varde_data.repos.calls import CallsRepository, MemoryCalls


def open_calls(root: Path, backend_name: str | None = None) -> CallsRepository:
    """Open the calls backend named by the argument or the learn store marker."""
    backend_name = resolve_backend(root, "calls", backend_name)
    if backend_name == "memory":
        return MemoryCalls()
    if backend_name == "files":
        module = importlib.import_module("varde_data.backends.files.calls")
        return cast("CallsRepository", module.FilesCalls(root))
    if backend_name == "sqlite":
        return cast("CallsRepository", load_sqlite_backend("calls")(root))
    raise ValueError(f"unknown calls backend: {backend_name}")
