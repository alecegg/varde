"""Shared command input reading."""

import sys
from pathlib import Path


def read_input(file: Path | str | None = None) -> bytes:
    if file is None:
        data = sys.stdin.buffer.read()
    else:
        path = Path(file)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise OSError(f"failed to read input file {path}") from exc
    if not data:
        raise ValueError("concept document is empty")
    return data
