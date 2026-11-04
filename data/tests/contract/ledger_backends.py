from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlite_ledger import factory as sqlite_factory
from varde_data.backends.files.ledger import FilesLedger
from varde_data.repos.ledger import LedgerRepository
from varde_data.testing import MemoryLedger


@dataclass(frozen=True)
class Backend:
    name: str
    factory: Callable[[Path], LedgerRepository]


def backend_registry() -> dict[str, Backend]:
    return {
        "memory": Backend("memory", MemoryLedger),
        "files": Backend("files", FilesLedger),
        "sqlite": Backend("sqlite", sqlite_factory),
    }
