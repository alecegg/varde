"""Pure projections from daily job snapshots to stored run fields."""

from __future__ import annotations

from typing import Any


def sweep_run_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Map a sweep snapshot to the outcome, error, and token store fields."""
    failures = snapshot.get("failures")
    error = snapshot.get("summary_error") if snapshot.get("state") == "failed" else None
    if snapshot.get("state") == "failed" and not error and failures:
        error = "; ".join(
            str(item.get("error", item)) if isinstance(item, dict) else str(item)
            for item in failures
        )
    tokens = snapshot.get("model_tokens")
    return {
        "outcome": "failed" if snapshot.get("state") == "failed" else "succeeded",
        "error": str(error)[:500] if error else None,
        "model_tokens": (
            tokens if isinstance(tokens, int) and not isinstance(tokens, bool) else None
        ),
    }


def review_run_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Map a review snapshot to the outcome, token, and cost store fields."""
    return {
        "outcome": "failed" if snapshot.get("state") == "failed" else "succeeded",
        "error": str(snapshot["error"])[:500] if snapshot.get("error") else None,
        "model_tokens": _optional_nonnegative_int(snapshot.get("model_tokens")),
        "cost_usd": _optional_nonnegative_number(snapshot.get("cost_usd")),
    }


def _optional_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _optional_nonnegative_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    return None


def soak_run_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Map a soak snapshot to the outcome, error, and token store fields."""
    error = snapshot.get("error")
    return {
        "outcome": "failed" if snapshot.get("state") == "failed" else "succeeded",
        "error": str(error)[:500] if error else None,
        "model_tokens": None,
    }
