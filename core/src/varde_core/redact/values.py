"""Collect secret-named environment and dotenv values for literal redaction."""

from __future__ import annotations

import os
from pathlib import Path

from . import SecretValue

_SECRET_MARKERS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "PRIVATE",
)
_MIN_VALUE_LEN = 8


def _is_secret_name(name: str) -> bool:
    upper = name.upper()
    return any(marker in upper for marker in _SECRET_MARKERS)


def _is_common_literal(value: str) -> bool:
    if value.lower() in {"true", "false"}:
        return True
    if value != value.strip() or "_" in value:
        return False
    try:
        float(value)
    except ValueError:
        return False
    return True


def _keep(name: str, value: str) -> SecretValue | None:
    if not name or len(value) < _MIN_VALUE_LEN or _is_common_literal(value):
        return None
    return SecretValue(name, value)


def _sorted_deduped(values: list[SecretValue]) -> list[SecretValue]:
    return sorted(set(values), key=lambda item: (item.name, item.value))


def from_environment() -> list[SecretValue]:
    values = []
    for name, value in os.environ.items():
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            continue
        if _is_secret_name(name) and (secret := _keep(name, value)) is not None:
            values.append(secret)
    return _sorted_deduped(values)


def _strip_comment(value: str) -> str:
    if value and value[0] in "\"'":
        end = value.find(value[0], 1)
        if end >= 0:
            return value[1:end]
    after_whitespace = True
    for index, char in enumerate(value):
        if char == "#" and after_whitespace:
            return value[:index].rstrip()
        after_whitespace = char.isspace()
    return value


def _parse_line(line: str) -> SecretValue | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export") and len(line) > 6 and line[6] in " \t":
        line = line[6:].lstrip()
    if "=" not in line:
        return None
    name, value = line.split("=", 1)
    return _keep(name.strip(), _strip_comment(value.strip()))


def from_dotenv(path: str | Path) -> list[SecretValue]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError, UnicodeError:
        return []
    return _sorted_deduped(
        [value for line in text.split("\n") if (value := _parse_line(line)) is not None]
    )


def _dotenv_files(root: str | Path) -> list[Path]:
    try:
        return sorted(
            path
            for path in Path(root).iterdir()
            if path.is_file() and (path.name == ".env" or path.name.startswith(".env."))
        )
    except OSError:
        return []


def collect(root: str | Path) -> list[SecretValue]:
    values = from_environment()
    for path in _dotenv_files(root):
        values.extend(from_dotenv(path))
    return _sorted_deduped(values)


__all__ = ["collect", "from_dotenv", "from_environment"]
