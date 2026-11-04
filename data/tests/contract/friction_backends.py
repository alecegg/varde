"""Backends exercised by the friction repository contract."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlite_friction import factory as sqlite_factory
from sqlite_friction import read_log as sqlite_read_log
from varde_data.backends.files.friction import FilesFriction
from varde_data.friction_events import replay
from varde_data.records.friction import Event
from varde_data.repos.friction import FrictionRepository
from varde_data.testing import MemoryFriction


@dataclass(frozen=True)
class Backend:
    name: str
    factory: Callable[[Path], FrictionRepository]
    log_path: Callable[[Path], Path]
    read_log: Callable[[Path], bytes]
    torn_tails: bool = True

    def events(self, root: Path) -> list[Event]:
        """Replay the stored log, whatever its storage."""
        return replay(self.read_log(root).decode().splitlines(keepends=True)).events


def _read_file_log(root: Path) -> bytes:
    path = root / "friction.jsonl"
    return path.read_bytes() if path.exists() else b""


def backend_registry() -> dict[str, Backend]:
    def log_path(root: Path) -> Path:
        return root / "friction.jsonl"

    return {
        "memory": Backend("memory", MemoryFriction, log_path, _read_file_log),
        "files": Backend("files", FilesFriction, log_path, _read_file_log),
        "sqlite": Backend(
            "sqlite", sqlite_factory, log_path, sqlite_read_log, torn_tails=False
        ),
    }
