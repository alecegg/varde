"""Allowlisted `config.toml` keys: read with defaults, write with validation."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import TOMLKitError

from varde_data.config import _atomic_write
from varde_data.errors import Invalid
from varde_data.locking import blocking_file_lock


@dataclass(frozen=True)
class ConfigKey:
    """A display or behavior setting that a remote client may change."""

    name: str
    default: int


# Never add `serve.*` (allow_edit, bind, port, hosts) or anything under `runner`:
# a token holder could otherwise grant itself write access.
ALLOWED_KEYS: tuple[ConfigKey, ...] = (
    ConfigKey("orchestration.stall_minutes", 60),
    ConfigKey("orchestration.wake_timeout_seconds", 10),
    ConfigKey("orchestration.wake_max_failures", 3),
    ConfigKey("memory.budget", 1200),
    ConfigKey("memory.scope_warn", 50),
)
_BY_NAME = {key.name: key for key in ALLOWED_KEYS}


def find_key(name: str) -> ConfigKey:
    try:
        return _BY_NAME[name]
    except KeyError:
        raise Invalid(f"config key not allowed: {name}") from None


def check_value(key: ConfigKey, value: Any) -> int:
    """Return `value` when it is a positive integer, else raise Invalid."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise Invalid(f"{key.name} must be a positive integer")
    return value


def _table(document: Any, group: str) -> dict[str, Any]:
    table = document.get(group)
    return table if isinstance(table, dict) else {}


def read_allowed(config_dir: Path) -> list[dict[str, Any]]:
    """Return every allowlisted key with its current value and default."""
    try:
        document = tomllib.loads((config_dir / "config.toml").read_text("utf-8"))
    except OSError, ValueError:
        document = {}
    rows = []
    for key in ALLOWED_KEYS:
        group, _, leaf = key.name.partition(".")
        value = _table(document, group).get(leaf)
        usable = isinstance(value, int) and not isinstance(value, bool) and value > 0
        rows.append(
            {
                "key": key.name,
                "value": value if usable else key.default,
                "default": key.default,
            }
        )
    return rows


def write_allowed(config_dir: Path, name: str, value: Any) -> int:
    """Set one allowlisted key, keeping comments and other tables."""
    key = find_key(name)
    checked = check_value(key, value)
    path = config_dir / "config.toml"
    group, _, leaf = key.name.partition(".")
    try:
        with blocking_file_lock(path.with_name("config.toml.lock"), mode=0o600):
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            document = tomlkit.parse(text)
            table = document.get(group)
            if not isinstance(table, dict):
                table = tomlkit.table()
                document[group] = table
            table[leaf] = checked
            _atomic_write(path, tomlkit.dumps(document))
    except (OSError, ValueError, TOMLKitError) as exc:
        raise Invalid(f"cannot update {path}: {exc}") from exc
    return checked
