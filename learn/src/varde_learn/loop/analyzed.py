"""Learn seam over the analyzed-session ledger in ``varde_data``."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from varde_data.ledger import open_ledger


def read_all(store_dir: Path) -> list[dict[str, Any]]:
    """Return the latest ledger row for each harness and session pair."""
    return [
        {key: value for key, value in asdict(row).items() if value is not None}
        for row in open_ledger(store_dir).analyzed()
    ]


def seen(store_dir: Path, harness: str) -> set[str]:
    """Return session IDs marked for one harness."""
    return open_ledger(store_dir).seen(harness)


def mark(  # noqa: PLR0913
    store_dir: Path,
    harness: str,
    session_id: str,
    when: str,
    summary: str,
    metrics: dict[str, Any] | None = None,
    *,
    friction_added: list[str] | None = None,
) -> None:
    """Append one complete ledger row."""
    open_ledger(store_dir).mark(
        harness, session_id, when, summary, metrics, friction_added
    )
