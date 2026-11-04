"""Backend-neutral API for the analyzed-session ledger."""

from datetime import date
from typing import Any, Protocol

from varde_data.records.ledger import Digest, LedgerRow


class LedgerRepository(Protocol):
    def mark(
        self,
        harness: str,
        session: str,
        when: str,
        summary: str,
        metrics: dict[str, Any] | None = None,
        friction_added: list[str] | None = None,
    ) -> None: ...

    def analyzed(self) -> list[LedgerRow]: ...
    def seen(self, harness: str) -> set[str]: ...
    def write_digest(
        self, run_date: date, text: str, candidates: list[dict[str, Any]]
    ) -> None: ...
    def read_digest(self, run_date: date) -> Digest | None: ...
