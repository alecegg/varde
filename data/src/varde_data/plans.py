"""Factory for selecting a plan repository backend."""

from pathlib import Path

from varde_data.backends.files.plans import FilesPlans
from varde_data.backends.sqlite.plans import SqlitePlans
from varde_data.repos.plans import PlanRepositoryReader


def open_plans(working_dir: Path, backend_name: str = "files") -> PlanRepositoryReader:
    if backend_name == "memory":
        from varde_data.testing import MemoryPlans

        return MemoryPlans()
    if backend_name == "files":
        return FilesPlans(working_dir)
    if backend_name == "sqlite":
        return open_fresh_plans(working_dir)
    raise ValueError(f"unknown plans backend: {backend_name}")


def open_fresh_plans(working_dir: Path) -> SqlitePlans:
    """Open a current SQLite snapshot for command-line use."""
    plans = SqlitePlans(working_dir)
    plans.refresh()
    return plans


def open_indexed_plans(working_dir: Path) -> SqlitePlans:
    """Open the last published SQLite snapshot without scanning source files."""
    return SqlitePlans(working_dir)
