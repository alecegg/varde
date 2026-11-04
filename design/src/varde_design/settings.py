"""Project settings: neutral defaults, validation, and the varde-design.toml loader."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from .registry import PROFILES, RULES_BY_ID

CONFIG_NAME = "varde-design.toml"


class SettingsError(ValueError):
    """Raised for an unreadable file, unknown key, or invalid value."""


@dataclass(frozen=True)
class Settings:
    token_files: tuple[str, ...] = ()
    spacing_scale: tuple[int, ...] | None = None
    font_size_scale: tuple[int, ...] | None = None
    min_target_px: int = 44
    min_text_px: int = 12
    min_ui_text_px: int = 11
    max_line_chars: int = 75
    min_line_chars: int = 45
    max_motion_ms: int = 300
    widths: tuple[int, ...] = (390, 768, 1440)
    color_roles: dict[str, str] = field(default_factory=dict)
    profile: str = "core"
    edge_padding_px: int = 16
    ignore: tuple[str, ...] = ()
    ignore_console: tuple[str, ...] = ()


_INT_KEYS = (
    "min_target_px",
    "min_text_px",
    "min_ui_text_px",
    "max_line_chars",
    "min_line_chars",
    "max_motion_ms",
    "edge_padding_px",
)
_INT_LIST_KEYS = ("spacing_scale", "font_size_scale", "widths")
_STR_LIST_KEYS = ("token_files", "ignore", "ignore_console")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _positive_int(key: str, value: object) -> int:
    if not _is_int(value) or value <= 0:  # type: ignore[operator]
        raise SettingsError(f"{key}: expected a positive integer, got {value!r}")
    return value  # type: ignore[return-value]


def _int_list(key: str, value: object) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise SettingsError(f"{key}: expected a non-empty list of integers")
    return tuple(_positive_int(key, item) for item in value)


def _str_list(key: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SettingsError(f"{key}: expected a list of strings")
    return tuple(value)


def _color_roles(value: object) -> dict[str, str]:
    is_table = isinstance(value, dict)
    if not is_table or not all(isinstance(v, str) for v in value.values()):  # type: ignore[union-attr]
        raise SettingsError(
            "color_roles: expected a table of role = token name strings"
        )
    return dict(value)  # type: ignore[arg-type]


def _profile(value: object) -> str:
    if value not in PROFILES:
        raise SettingsError(
            f"profile: expected one of {', '.join(PROFILES)}, got {value!r}"
        )
    return str(value)


def _ignore_ids(ids: tuple[str, ...]) -> tuple[str, ...]:
    unknown = [rule_id for rule_id in ids if rule_id not in RULES_BY_ID]
    if unknown:
        raise SettingsError(f"ignore: unknown rule id {', '.join(unknown)}")
    return ids


def _console_patterns(patterns: tuple[str, ...]) -> tuple[str, ...]:
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as error:
            raise SettingsError(
                f"ignore_console: bad regex {pattern!r}: {error}"
            ) from error
    return patterns


def _convert(key: str, value: object) -> object:
    if key in _INT_KEYS:
        return _positive_int(key, value)
    if key in _INT_LIST_KEYS:
        return _int_list(key, value)
    if key == "ignore":
        return _ignore_ids(_str_list(key, value))
    if key == "ignore_console":
        return _console_patterns(_str_list(key, value))
    if key in _STR_LIST_KEYS:
        return _str_list(key, value)
    if key == "color_roles":
        return _color_roles(value)
    return _profile(value)


def parse_settings(data: dict[str, object]) -> Settings:
    """Build Settings from parsed TOML; an unknown key or bad value is an error."""
    known = {item.name for item in fields(Settings)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise SettingsError(f"unknown setting: {', '.join(unknown)}")
    return Settings(**{key: _convert(key, value) for key, value in data.items()})  # type: ignore[arg-type]


def find_config(root: Path) -> Path | None:
    candidate = root / CONFIG_NAME
    return candidate if candidate.is_file() else None


def load_settings(path: Path) -> Settings:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise SettingsError(f"{path}: cannot read: {error}") from error
    except tomllib.TOMLDecodeError as error:
        raise SettingsError(f"{path}: invalid TOML: {error}") from error
    return parse_settings(data)
