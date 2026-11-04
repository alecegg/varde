"""API errors and JSON-safe conversion."""

from __future__ import annotations

import dataclasses
import enum
from pathlib import Path
from typing import Any


class ApiError(Exception):
    """A request the handlers refuse: HTTP status, short code, message."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def plain(value: Any) -> Any:
    """Convert dataclasses, paths, enums, tuples and sets to JSON values."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [plain(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    return value
