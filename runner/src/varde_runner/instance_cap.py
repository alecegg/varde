"""Pure helpers for counting live runner instances."""

from collections.abc import Mapping, Sequence
from typing import Any


class InstanceCapError(RuntimeError):
    """Raised when starting another session would exceed the live cap."""

    def __init__(self, live: int, max_live: int) -> None:
        super().__init__(f"live instance cap reached ({live}/{max_live})")
        self.live = live
        self.max_live = max_live


def live_count(agent_rows: Sequence[Mapping[str, Any]]) -> int:
    """Count agent rows whose lifecycle is still live."""
    return sum(
        row.get("lifecycle") not in {"completed", "archived"} for row in agent_rows
    )


def over_cap(live: int, max_live: int) -> bool:
    """Return whether another instance would exceed the configured cap."""
    return live >= max_live
