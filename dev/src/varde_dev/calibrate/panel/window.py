"""Usage-window validation for guarded panel runs."""

import datetime as dt
import tomllib
from pathlib import Path
from typing import TypedDict


class UsageWindow(TypedDict):
    start: dt.datetime
    end: dt.datetime
    cap_per_hour: int
    stop_rule: str


def load_current_window(path: str | Path, now: dt.datetime) -> UsageWindow:
    """Read and validate an explicitly supplied usage window against a clock."""
    with Path(path).open("rb") as stream:
        data = tomllib.load(stream)
    try:
        start = _parse_time(data["start"])
        end = _parse_time(data["end"])
        cap = data["cap_per_hour"]
        stop_rule = data["stop_rule"]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid usage window; see panel/WINDOW_FILE.md") from error
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        raise ValueError("usage window cap_per_hour must be a positive integer")
    if not isinstance(stop_rule, str) or not stop_rule.strip():
        raise ValueError("usage window stop_rule must be a non-empty string")
    if now.tzinfo is None or start.tzinfo is None or end.tzinfo is None:
        raise ValueError("usage window timestamps and clock must include a timezone")
    if not start <= now < end:
        raise ValueError("usage window is not current")
    return {"start": start, "end": end, "cap_per_hour": cap, "stop_rule": stop_rule}


def _parse_time(value: object) -> dt.datetime:
    if not isinstance(value, str):
        raise TypeError("timestamps must be strings")
    return dt.datetime.fromisoformat(value)
