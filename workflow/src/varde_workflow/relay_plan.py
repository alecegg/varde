"""Workflow adapters for the shared relay planning views."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from varde_data.views import relay_plan as _view


def _context(state: dict[str, Any]):
    working = state.get("working")
    if not isinstance(working, str | Path):
        return None, None
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    data = open_data(Path(working), load_data_config())
    resolved = dict(state)
    resolved["concluded_addresses"] = sorted(data.messages.concluded_addresses())
    return resolved, data.addresses.resolve_alias


def plan(
    state: dict[str, Any], now: datetime, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Plan actions using the repository-backed slot and conclusion views."""
    resolved, resolver = _context(state)
    return _view.plan(resolved or state, now, config, resolve_reader=resolver)


def next_due(
    state: dict[str, Any], now: datetime, config: dict[str, Any] | None = None
) -> datetime | None:
    """Return the next repository-aware planning deadline."""
    resolved, resolver = _context(state)
    return _view.next_due(resolved or state, now, config, resolve_reader=resolver)


def __getattr__(name: str) -> Any:
    """Keep the historical pure helper names available to workflow callers."""
    return getattr(_view, name)
