"""Lazy registry for decision repository contract backends."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from varde_data.backends.memory.decisions import MemoryDecisions
from varde_data.repos.decisions import DecisionRepository


@dataclass(frozen=True)
class Backend:
    name: str
    factory: Callable[[Path], DecisionRepository]


def _memory(root: Path) -> DecisionRepository:
    return MemoryDecisions(root / "decision-notes")


def backend_registry() -> dict[str, Backend]:
    registry = {"memory": Backend("memory", _memory)}
    module_name = "varde_data.backends.sqlite.decisions"
    try:
        available = importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        available = False
    if available:
        module = importlib.import_module(module_name)
        registry["sqlite"] = Backend("sqlite", module.SqliteDecisions)
    return registry
