"""User memory configuration loading, editing, and persistence."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from varde_core.paths import varde_config_dir

CONFIG_FILE = "config.toml"
LEGACY_CONFIG_FILE = "paths.toml"
DEFAULT_WAKE_TIMEOUT_SECONDS = 10
DEFAULT_WAKE_MAX_FAILURES = 3
DEFAULT_MEMORY_BUDGET_CHARS = 1200
DEFAULT_SCOPE_WARN = 50


class MemoryConfigError(ValueError):
    """A memory config could not be read, parsed, or written."""


def config_path() -> Path:
    """Return the user-scoped config.toml path."""
    return varde_config_dir() / CONFIG_FILE


@dataclass
class Orchestration:
    """Lenient access to the optional [orchestration] settings."""

    values: dict[str, Any] = field(default_factory=dict)
    not_a_table: bool = False

    def wake_command(self) -> tuple[list[str], str | None]:
        if self.not_a_table:
            return [], "`orchestration` is not a table"
        value = self.values.get("wake_command")
        if value is None:
            return [], None
        if isinstance(value, list):
            if all(isinstance(item, str) for item in value):
                return list(value), None
            return [], "array contains a non-string value"
        return [], f"{_toml_value_text(value)} is not an array of strings"

    def wake_timeout_seconds(self) -> tuple[int, str | None]:
        return _positive_setting(
            self, "wake_timeout_seconds", DEFAULT_WAKE_TIMEOUT_SECONDS
        )

    def wake_max_failures(self) -> tuple[int, str | None]:
        return _positive_setting(self, "wake_max_failures", DEFAULT_WAKE_MAX_FAILURES)


@dataclass
class Memory:
    """Lenient access to the optional [memory] settings."""

    values: dict[str, Any] = field(default_factory=dict)
    not_a_table: bool = False

    def budget_chars(self) -> tuple[int, str | None]:
        return _positive_setting(
            self, "budget", DEFAULT_MEMORY_BUDGET_CHARS, table="memory"
        )

    def scope_warn(self) -> tuple[int, str | None]:
        return _positive_setting(self, "scope_warn", DEFAULT_SCOPE_WARN, table="memory")

    def shared(self) -> tuple[str, str | None]:
        if self.not_a_table:
            return "", "`memory` is not a table"
        value = self.values.get("shared")
        if value is None:
            return "", "`[memory] shared` is not set"
        if isinstance(value, str) and value.strip():
            return value, None
        return "", f"{_toml_value_text(value)} is not a non-empty string"


def _positive_setting(
    config: Orchestration | Memory,
    key: str,
    default: int,
    table: str = "orchestration",
) -> tuple[int, str | None]:
    if config.not_a_table:
        return default, f"`{table}` is not a table"
    value = config.values.get(key)
    if value is None:
        return default, None
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value, None
    return default, f"{_toml_value_text(value)} is not a positive integer"


def _toml_value_text(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value_text(item) for item in value) + "]"
    return str(value)


def _wrapper[T: (Orchestration, Memory)](kind: type[T], raw: Any) -> T:
    if raw is None:
        return kind()
    if isinstance(raw, dict):
        return kind(dict(raw))
    return kind(not_a_table=True)


@dataclass
class Config:
    """Parsed TOML document with lenient orchestration settings."""

    document: Any = field(default_factory=dict)
    orchestration: Orchestration = field(default_factory=Orchestration)
    memory: Memory = field(default_factory=Memory)

    @classmethod
    def from_toml(cls, text: str) -> Config:
        try:
            document = tomllib.loads(text)
        except (tomllib.TOMLDecodeError, TypeError) as exc:
            raise MemoryConfigError(f"failed to parse memory config: {exc}") from exc
        orchestration = _wrapper(Orchestration, document.get("orchestration"))
        return cls(document, orchestration, _wrapper(Memory, document.get("memory")))

    def is_empty(self) -> bool:
        return not bool(self.document)


def load_config() -> Config:
    """Load config.toml, falling back to legacy paths.toml when absent."""
    path = config_path()
    if not path.exists():
        path = path.with_name(LEGACY_CONFIG_FILE)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Config()
    except OSError as exc:
        raise MemoryConfigError(f"failed to read memory config {path}: {exc}") from exc
    try:
        return Config.from_toml(text)
    except MemoryConfigError as exc:
        raise MemoryConfigError(f"failed to parse memory config {path}: {exc}") from exc


def holds_seeded_hooks_or_comments(path: Path) -> bool:
    """Whether a config contains seeded hook tables or user comments."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(line.lstrip().startswith(("#", "[hooks")) for line in lines)


def merge_toml_text(existing: str, fresh: str) -> str:
    """Merge fresh values while retaining unchanged comments and formatting."""
    from varde_learn.knowledge.formats import edit_toml

    return edit_toml(existing, fresh)


def save_config(config: Config) -> Path:
    """Atomically persist config, preserving comments and seeded hooks."""
    import tomlkit

    path = config_path()
    legacy = path.with_name(LEGACY_CONFIG_FILE)
    if config.is_empty() and not holds_seeded_hooks_or_comments(path):
        path.unlink(missing_ok=True)
        legacy.unlink(missing_ok=True)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = tomlkit.dumps(config.document)
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = None
    except OSError as exc:
        raise MemoryConfigError(f"failed to read memory config {path}: {exc}") from exc
    text = merge_toml_text(existing, fresh) if existing is not None else fresh
    fd, temporary = tempfile.mkstemp(prefix=f".{CONFIG_FILE}.tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise MemoryConfigError(f"failed to write memory config {path}: {exc}") from exc
    legacy.unlink(missing_ok=True)
    return path
