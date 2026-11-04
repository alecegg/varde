"""Append-only ``cli_calls.jsonl`` backend."""

import json
import os
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from varde_data.errors import LearnStoreIo
from varde_data.learn_store_mode import files_writer
from varde_data.repos.calls import CALLS_NAME, CallRecord, rows_since

APPEND_LOCK_TIMEOUT = 0.5


def iter_rows(path: Path) -> Iterator[CallRecord]:
    """Yield each line that is a JSON object; skip torn and malformed lines."""
    with path.open("rb") as handle:
        for line in handle:
            row = parse_line(line)
            if row is not None:
                yield row


def parse_line(line: bytes) -> CallRecord | None:
    try:
        value = json.loads(line)
    except ValueError, RecursionError:
        return None
    return value if isinstance(value, dict) else None


class FilesCalls:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / CALLS_NAME

    def append(self, row: Mapping[str, Any]) -> None:
        line = (json.dumps(row, separators=(",", ":")) + "\n").encode()
        self.root.mkdir(parents=True, exist_ok=True)
        with files_writer(self.root, "calls", timeout=APPEND_LOCK_TIMEOUT):
            _append_line(self.path, line)

    def read(self) -> list[CallRecord]:
        try:
            return self.read_strict()
        except LearnStoreIo:
            return []

    def read_strict(self, since: datetime | None = None) -> list[CallRecord]:
        try:
            return rows_since(iter_rows(self.path), since)
        except FileNotFoundError:
            return []
        except (OSError, UnicodeError) as error:
            raise LearnStoreIo("read CLI calls", self.path, _os_error(error)) from error


def _os_error(error: OSError | UnicodeError) -> OSError:
    return error if isinstance(error, OSError) else OSError(str(error))


def _append_line(path: Path, line: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        prefix = b"" if _ends_cleanly(path) else b"\n"
        data = prefix + line
        if os.write(descriptor, data) != len(data):
            raise OSError("short write while appending CLI call")
    finally:
        os.close(descriptor)


def _ends_cleanly(path: Path) -> bool:
    if not path.stat().st_size:
        return True
    with path.open("rb") as existing:
        existing.seek(-1, os.SEEK_END)
        return existing.read(1) == b"\n"
