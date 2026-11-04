"""Factories for the shared file, memory, and SQLite plans contract."""

from pathlib import Path

from varde_data.backends.files.plans import FilesPlans
from varde_data.backends.sqlite.plans import SqlitePlans
from varde_data.testing import MemoryPlans


def open_backend(name: str, working: Path):
    """Open one backend over the same file-backed fixture tree."""
    if name == "files":
        return FilesPlans(working)
    if name == "memory":
        memory = MemoryPlans()
        memory.records.extend(FilesPlans(working).list(include_archived=True).records)
        return memory
    if name == "sqlite":
        plans = SqlitePlans(working)
        plans.refresh()
        return plans
    raise ValueError(f"unknown plans backend: {name}")
