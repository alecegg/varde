"""Persistent dashboard settings."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

DEFAULT_APP_ICON = "slate-bronze"
APP_ICON_OPTIONS = (
    {"id": "slate-bronze", "name": "Slate bronze"},
    {"id": "dark", "name": "Dark slate bronze"},
)
APP_ICON_IDS = frozenset(option["id"] for option in APP_ICON_OPTIONS)


def validate_app_icon(value: Any) -> str:
    if not isinstance(value, str) or value not in APP_ICON_IDS:
        raise ValueError("invalid app_icon")
    return value


def read_settings(path: Path) -> dict[str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return {"app_icon": DEFAULT_APP_ICON}
        return {"app_icon": validate_app_icon(value.get("app_icon"))}
    except OSError, UnicodeError, json.JSONDecodeError, ValueError:
        return {"app_icon": DEFAULT_APP_ICON}


def write_settings(path: Path, app_icon: Any) -> dict[str, str]:
    selected = validate_app_icon(app_icon)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".settings-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"app_icon": selected}, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary)
    return {"app_icon": selected}
