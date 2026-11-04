"""Persistent chat pin preferences."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

DEFAULT_PINS = ["manager", "builder", "reviewer"]
MAX_PINS = 100
MAX_PIN_LENGTH = 200
MAX_PINS_BODY_BYTES = 32_768


def read_pins(path: Path) -> list[str]:
    if not path.exists():
        return DEFAULT_PINS.copy()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, json.JSONDecodeError:
        return []
    if not isinstance(value, dict):
        return []
    pins = value.get("pins")
    return _valid_pins(pins) if isinstance(pins, list) else []


def write_pins(path: Path, pins: Any) -> list[str]:
    selected = _valid_pins(pins)
    if (
        not isinstance(pins, list)
        or len(pins) > MAX_PINS
        or len(selected) != len(pins)
        or any(len(pin) > MAX_PIN_LENGTH for pin in selected)
    ):
        raise ValueError("pins must be a list of unique non-empty strings")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".pins-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"pins": selected}, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary)
    return selected


def _valid_pins(value: list[Any]) -> list[str]:
    if any(not isinstance(item, str) or not item.strip() for item in value):
        return []
    pins = [item.strip() for item in value]
    return list(dict.fromkeys(pins))
