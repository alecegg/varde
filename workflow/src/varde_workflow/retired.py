"""Read and write relay retirement records."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from varde_data.config import load_data_config
from varde_data.open import open_data


def load(working: str | Path) -> dict[str, str]:
    """Return retired address and mailman-token timestamps."""
    repository = open_data(Path(working), load_data_config()).addresses
    return dict(repository.retired_records())


def retire(
    working: str | Path,
    addresses: set[str],
    tokens: set[str],
    now: datetime,
) -> dict[str, str]:
    """Persist retirement timestamps for addresses and mailman tokens."""
    repository = open_data(Path(working), load_data_config()).addresses
    repository.retire(addresses, tokens, now)
    return dict(repository.retired_records())
