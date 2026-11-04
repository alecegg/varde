"""Compare token spend snapshots with a fixed noise threshold."""

from __future__ import annotations

from datetime import datetime
from typing import Any

NOISE_THRESHOLD = 0.05


def compare(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """Compare aggregate metrics; movement under five percent is unchanged."""
    if previous is None:
        return {"status": "no_previous", "message": "No previous token-spend snapshot."}
    old_window = previous.get("window")
    new_window = current.get("window")
    if not _comparable_windows(old_window, new_window):
        return {
            "status": "not_comparable",
            "message": (
                "Previous token-spend snapshot has a different or unknown window; "
                "metrics were not compared."
            ),
        }
    old = previous.get("totals", {})
    new = current.get("totals", {})
    metrics = {}
    for key in ("input", "cache_read", "cache_write", "output", "weighted", "calls"):
        before, after = old.get(key), new.get(key)
        if (
            isinstance(before, bool)
            or isinstance(after, bool)
            or not isinstance(before, (int, float))
            or not isinstance(after, (int, float))
        ):
            metrics[key] = {"change": "unavailable", "delta": None}
            continue
        delta = after - before
        relative = delta / before if before else (0.0 if after == 0 else 1.0)
        metrics[key] = {
            "previous": before,
            "current": after,
            "delta": delta,
            "change": "unchanged"
            if abs(relative) < NOISE_THRESHOLD
            else "up"
            if delta > 0
            else "down",
        }
    return {
        "status": "compared",
        "noise_threshold": NOISE_THRESHOLD,
        "metrics": metrics,
    }


def _comparable_windows(previous: Any, current: Any) -> bool:
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return False
    try:
        previous_start = datetime.fromisoformat(previous["start"])
        previous_end = datetime.fromisoformat(previous["end"])
        current_start = datetime.fromisoformat(current["start"])
        current_end = datetime.fromisoformat(current["end"])
    except KeyError, TypeError, ValueError:
        return False
    return (
        abs(
            (previous_end - previous_start).total_seconds()
            - (current_end - current_start).total_seconds()
        )
        <= 1
    )
