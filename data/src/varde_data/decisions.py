"""Factories and watched paths for decision repositories."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from varde_data.repos.decisions import DecisionRepository

if TYPE_CHECKING:
    from varde_data.backends.sqlite.decisions import SqliteDecisions


def open_decisions(
    root: Path,
    backend_name: str = "sqlite",
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> DecisionRepository:
    if backend_name == "sqlite":
        from varde_data.backends.sqlite.decisions import SqliteDecisions

        return SqliteDecisions(root, clock)
    if backend_name == "memory":
        from varde_data.backends.memory.decisions import MemoryDecisions

        return MemoryDecisions(root / "notes", clock)
    raise ValueError(f"unknown decisions backend: {backend_name}")


def open_sqlite_decisions(
    root: Path, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
) -> SqliteDecisions:
    """Open the production backend when a caller needs its connection and lock."""
    from varde_data.backends.sqlite.decisions import SqliteDecisions

    return SqliteDecisions(root, clock)


def decision_store_files(root: Path) -> tuple[Path, ...]:
    database = root / "decisions.sqlite3"
    return (
        database,
        Path(f"{database}-wal"),
        Path(f"{database}-shm"),
        root / "decisions.audit.jsonl",
    )
