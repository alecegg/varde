"""Watermark and retention window for the CLI call log."""

from __future__ import annotations

import sqlite3
import sys
import tomllib
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from varde_data import calls_store
from varde_data.errors import DataError
from varde_data.learn_store_mode import backend_for, shared_store_lock
from varde_data.repos.calls import CALLS_NAME

from .calls import CallRow, parse_timestamp
from .errors import StoreConfig, StoreIo
from .store.paths import resolve_store_dir

DEFAULT_DAYS = 30
CONFIG_NAME = "sweep.toml"


def note_calls_used(rows: Iterable[CallRow]) -> None:
    """Advance the used-through mark to the latest ``ts`` among ranked rows.

    A summarizing read calls this after its report is built. Failure only
    warns: a report must not fail because the used-through mark could not be saved.
    """
    stamps = (parse_timestamp(row["ts"]) for row in rows)
    latest = max((stamp for stamp in stamps if stamp is not None), default=None)
    if latest is None:
        return
    try:
        root = resolve_store_dir()
        if backend_for(root, "calls") == "sqlite":
            calls_store.mark_used(root, latest.astimezone(UTC).isoformat())
    except (OSError, sqlite3.Error, DataError, StoreConfig, StoreIo) as error:
        sys.stderr.write(
            f"warning: could not save the calls used-through mark: {error}\n"
        )


def retention_days() -> int:
    """Return ``[retention] calls_days`` from ``sweep.toml`` beside the store."""
    path = resolve_store_dir() / CONFIG_NAME
    if not path.is_file():
        return DEFAULT_DAYS
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"cannot read {path}: {error}") from error
    section = config.get("retention", {})
    if not isinstance(section, dict):
        raise ValueError(f"{path}: [retention] must be a table")  # noqa: TRY004
    days = section.get("calls_days", DEFAULT_DAYS)
    if isinstance(days, bool) or not isinstance(days, int) or days < 1:
        raise ValueError(f"{path}: retention calls_days must be a positive integer")
    return days


def window_exceeds_retention(window: timedelta | None) -> int | None:
    """Return the retention days when the window is longer; ``None`` otherwise.

    ``window`` ``None`` means all rows. A bad config skips the notice
    (``store prune`` reports the config error).
    """
    try:
        if backend_for(resolve_store_dir(), "calls") != "sqlite":
            return None  # nothing is pruned from the files backend
        days = retention_days()
    except ValueError, DataError, StoreConfig, StoreIo, OSError:
        return None
    return days if window is None or window > timedelta(days=days) else None


def report_meta(window: str, duration: timedelta | None) -> dict[str, object]:
    """Envelope meta for a report; warns and adds ``retention_days`` if too long."""
    meta: dict[str, object] = {"window": window}
    days = window_exceeds_retention(duration)
    if days is not None:
        sys.stderr.write(
            f"warning: the window is longer than the {days}-day calls retention; "
            "older calls may be missing\n"
        )
        meta["retention_days"] = days
    return meta


def prune_calls(
    root: Path, days: int, *, dry_run: bool = False, vacuum: bool = False
) -> dict[str, Any]:
    """Prune the calls table under the shared store lock; refuse unsafe stores."""
    if backend_for(root, "calls") != "sqlite":
        raise ValueError("calls is not on sqlite; prune applies only to sqlite")
    with shared_store_lock(root):
        if (root / CALLS_NAME).exists():
            raise ValueError(
                f"{CALLS_NAME} still exists; run `varde learn store retire "
                "--domain calls` first"
            )
        result = calls_store.prune(root, days, datetime.now(UTC), dry_run=dry_run)
        if vacuum and not dry_run:
            result["vacuum"] = calls_store.vacuum(root)
    return result
