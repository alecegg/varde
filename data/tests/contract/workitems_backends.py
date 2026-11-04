"""Lazy backend registry for work item contract tests."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from varde_data.backends.memory.workitems import MemoryWorkItems
from varde_data.repos.workitems import WorkItemRepository


@dataclass(frozen=True)
class Backend:
    name: str
    factory: Callable[[Path], WorkItemRepository]


def _memory(root: Path) -> WorkItemRepository:
    return MemoryWorkItems(root / "workitem-notes")


def backend_registry() -> dict[str, Backend]:
    registry = {"memory": Backend("memory", _memory)}
    module_name = "varde_data.backends.sqlite.workitems"
    try:
        available = importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        available = False
    if available:
        module = importlib.import_module(module_name)
        registry["sqlite"] = Backend("sqlite", module.SqliteWorkItems)
    return registry
