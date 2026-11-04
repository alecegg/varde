"""Guard the legacy files store against stale writers after cutover."""

from pathlib import Path

from varde_data.errors import Locked
from varde_data.store_mode import StoreModeRecord


def ensure_files_store_writable(working: Path, record: StoreModeRecord | None) -> None:
    if record is not None and record.primary == "sqlite" and record.mirror != "files":
        raise Locked("message store is SQLite-primary; refusing stale files writer")
