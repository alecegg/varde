"""Plain records for analyzed sessions and sweep digests."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LedgerRow:
    session: str
    harness: str
    analyzed_at: str
    summary: str | None = None
    metrics: dict[str, Any] | None = None
    friction_added: list[str] | None = None


@dataclass(frozen=True)
class Digest:
    date: str
    text: str
    candidates: Any
