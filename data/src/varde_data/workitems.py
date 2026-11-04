"""Factory and filesystem paths for work item repositories."""

from pathlib import Path

from varde_data.repos.workitems import WorkItemRepository


def open_workitems(root: Path, backend_name: str = "sqlite") -> WorkItemRepository:
    if backend_name == "sqlite":
        from varde_data.backends.sqlite.workitems import SqliteWorkItems

        return SqliteWorkItems(root)
    if backend_name == "memory":
        from varde_data.backends.memory.workitems import MemoryWorkItems

        return MemoryWorkItems(root / "workitem-notes")
    raise ValueError(f"unknown work items backend: {backend_name}")


def workitem_store_files(root: Path) -> tuple[Path, ...]:
    database = root / "workitems.sqlite3"
    return (
        database,
        Path(f"{database}-wal"),
        Path(f"{database}-shm"),
        root / "workitem-notes",
    )
