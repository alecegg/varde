"""Loud backend registry for the address repository contract."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from varde_data.backends.memory.addresses import MemoryAddresses
from varde_data.repos.addresses import AddressRepository

AddressBackendFactory = Callable[[Path], AddressRepository]


@dataclass(frozen=True)
class BackendCapabilities:
    multi_process: bool
    lock_timeout: bool
    append_only_events: bool
    lock_free_reads: bool
    relay_storage: bool


@dataclass(frozen=True)
class BackendRegistration:
    name: str
    factory: AddressBackendFactory
    capabilities: BackendCapabilities


def _available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if module_name == missing or module_name.startswith(missing + "."):
            return False
        raise


def backend_registry() -> dict[str, BackendRegistration]:
    registry = {
        "memory": BackendRegistration(
            "memory",
            lambda _working: MemoryAddresses(),
            BackendCapabilities(False, False, True, True, True),
        )
    }
    if _available("varde_data.backends.files.addresses"):
        importlib.import_module("varde_data.backends.files.addresses")
        module = importlib.import_module("files_addresses")
        factory = cast("Callable[[Path], AddressRepository]", module.factory)
        registry["files"] = BackendRegistration(
            "files", factory, BackendCapabilities(True, True, True, True, True)
        )
    if _available("sqlite_addresses"):
        module = importlib.import_module("sqlite_addresses")
        factory = cast("AddressBackendFactory", module.factory)
        registry["sqlite"] = BackendRegistration(
            "sqlite", factory, BackendCapabilities(True, True, True, True, True)
        )
    return registry
