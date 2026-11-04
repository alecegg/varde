"""Host-supplied doctor report sections."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DoctorEntry:
    line: str
    json: Any


@dataclass(frozen=True)
class DoctorSection:
    key: str
    entries: list[DoctorEntry]
