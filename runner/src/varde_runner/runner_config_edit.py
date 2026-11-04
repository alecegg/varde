"""Validate and safely edit the dashboard-managed runner config keys."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from typing import Any

from varde_runner import config
from varde_runner.config import ConfigError, parse_config
from varde_runner.guard_policy import validate_guard_role


@dataclass(frozen=True)
class Field:
    value_type: type
    minimum: int | None = None
    maximum: int | None = None


@dataclass(frozen=True)
class EditError:
    hint: str


ALLOWLIST = {
    "limits.max_live_instances": Field(int, 1, 64),
}
_TABLE_HEADER = re.compile(r"^\s*(\[\[?)\s*([A-Za-z0-9_.-]+)\s*(\]\]?)\s*(?:#.*)?$")
_ASSIGNMENT = re.compile(r"^(\s*)([A-Za-z0-9_-]+)(\s*=\s*)(.*)$")
_FORBIDDEN_NAMES = frozenset(
    {
        "key",
        "token",
        "secret",
        "password",
        "credential",
        "api",
        "env",
        "binary",
        "command",
        "path",
        "dir",
        "hook",
        "launch_roles",
    }
)
_FORBIDDEN_SUFFIXES = (
    "_key",
    "_token",
    "_secret",
    "_password",
    "_credential",
    "_credentials",
    "_env",
    "_binary",
    "_command",
    "_path",
    "_dir",
    "_hook",
)


def allowlist(registry: Any, text: str) -> dict[str, Field]:
    fields = dict(ALLOWLIST)
    if registry is not None:
        for table in registry.config_tables():
            if isinstance(table, str) and re.fullmatch(r"[A-Za-z0-9_-]+", table):
                fields[f"{table}.enabled"] = Field(bool)
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        parsed = {}
    bot_bounds = getattr(config, "BOT_CONFIG_BOUNDS", {})
    if isinstance(parsed.get("bot"), dict) and isinstance(bot_bounds, dict):
        for key, bounds in bot_bounds.items():
            if (
                isinstance(key, str)
                and isinstance(bounds, tuple)
                and len(bounds) == 2
                and all(isinstance(bound, int) for bound in bounds)
            ):
                fields[f"bot.{key}"] = Field(int, bounds[0], bounds[1])
    types = parsed.get("types", {})
    if isinstance(types, dict):
        for name in types:
            if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+", name):
                for key, value_type in (
                    ("harness", str),
                    ("model", str),
                    ("reasoning_effort", str),
                    ("fallback", list),
                ):
                    fields[f"types.{name}.{key}"] = Field(value_type)
    roles = parsed.get("roles", {})
    if isinstance(roles, dict):
        for name in roles:
            if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+", name):
                fields[f"roles.{name}.type"] = Field(str)
                if name == "guard":
                    fields["roles.guard.enabled"] = Field(bool)
    fields["policy.never_models"] = Field(list)
    fields["policy.allow_fallback_only_on"] = Field(list)
    return fields


def _registry_accepts(registry: Any, harness: str, key: str, value: Any) -> bool:
    choices = getattr(registry, "config_choices", None)
    if not callable(choices):
        return True
    try:
        supported = choices(harness)
    except KeyError, LookupError, ValueError:
        return False
    option_key = {
        "harness": "harnesses",
        "model": "models",
        "reasoning_effort": "reasoning_efforts",
    }.get(key)
    if option_key is None:
        return True
    values = supported.get(option_key, ()) if isinstance(supported, dict) else ()
    return value in values


def _valid_fallbacks(value: Any, registry: Any) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, dict) or set(item) - {
            "harness",
            "model",
            "reasoning_effort",
            "mode",
        }:
            return False
        for key in ("harness", "model", "reasoning_effort"):
            if not isinstance(item.get(key), str) or not _registry_accepts(
                registry, item["harness"], key, item[key]
            ):
                return False
    return True


def _candidate_has_registered_choices(text: str, registry: Any) -> bool:
    choices = getattr(registry, "config_choices", None)
    if not callable(choices):
        return True
    try:
        types = tomllib.loads(text).get("types", {})
    except tomllib.TOMLDecodeError:
        return False
    if not isinstance(types, dict):
        return False
    for type_data in types.values():
        if not isinstance(type_data, dict):
            return False
        harness = type_data.get("harness", "")
        for key in ("harness", "model", "reasoning_effort"):
            value = type_data.get(key)
            if not isinstance(value, str) or not _registry_accepts(
                registry, harness, key, value
            ):
                return False
        if not _valid_fallbacks(type_data.get("fallback", []), registry):
            return False
    return True


def _is_excluded(key: str) -> bool:
    leaf = key.casefold().split(".")[-1]
    return leaf in _FORBIDDEN_NAMES or leaf.endswith(_FORBIDDEN_SUFFIXES)


def validate(
    changes: dict[str, Any], registry: Any = None, text: str = ""
) -> dict[str, str]:
    fields = allowlist(registry, text)
    errors: dict[str, str] = {}
    for key, value in changes.items():
        if not isinstance(key, str) or _is_excluded(key):
            errors[str(key)] = "this key cannot be edited in Settings"
            continue
        field = fields.get(key)
        if field is None:
            errors[key] = "this key is not allowlisted"
            continue
        if field.value_type is bool:
            if not isinstance(value, bool):
                errors[key] = "must be a boolean"
            continue
        if field.value_type is str:
            if not isinstance(value, str) or not value:
                errors[key] = "must be a non-empty string"
                continue
            parts = key.split(".")
            if (
                len(parts) == 3
                and parts[0] == "types"
                and parts[2] in {"harness", "model", "reasoning_effort"}
            ):
                try:
                    current = tomllib.loads(text)["types"][parts[1]]
                    harness = (
                        value if parts[2] == "harness" else current.get("harness", "")
                    )
                except KeyError, tomllib.TOMLDecodeError:
                    errors[key] = "type settings are invalid"
                    continue
                if not _registry_accepts(registry, harness, parts[2], value):
                    errors[key] = "value is not available for this harness"
            continue
        if field.value_type is list:
            if key.endswith(".fallback"):
                if not _valid_fallbacks(value, registry):
                    errors[key] = "must be an ordered list of supported model settings"
            elif not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                errors[key] = "must be a list of strings"
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            errors[key] = "must be an integer"
        elif field.minimum is not None and value < field.minimum:
            errors[key] = f"must be at least {field.minimum}"
        elif field.maximum is not None and value > field.maximum:
            errors[key] = f"must be at most {field.maximum}"
    return errors


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        import json

        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_literal(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{ "
            + ", ".join(f"{key} = {_literal(item)}" for key, item in value.items())
            + " }"
        )
    return str(value)


def _comment_index(value: str) -> int:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\" and quote == '"':
            escaped = True
        elif quote is not None and char == quote:
            quote = None
        elif quote is None and char in {'"', "'"}:
            quote = char
        elif quote is None and char == "#":
            return index
    return len(value)


def _replace_value(line: str, key: str, value: Any) -> str | EditError:
    assignment = _ASSIGNMENT.match(line)
    if assignment is None or assignment.group(2) != key:
        return EditError(
            f"edit {key} by hand; its TOML assignment is not a simple line"
        )
    prefix = assignment.group(1) + assignment.group(2) + assignment.group(3)
    rhs = assignment.group(4)
    comment_at = _comment_index(rhs)
    before_comment, comment = rhs[:comment_at], rhs[comment_at:]
    trailing = before_comment[len(before_comment.rstrip()) :]
    return f"{prefix}{_literal(value)}{trailing}{comment}"


def _edit_table(text: str, table: str, key: str, value: Any) -> str | EditError:
    lines = text.splitlines(keepends=True)
    headers: list[tuple[int, bool]] = []
    for index, line in enumerate(lines):
        match = _TABLE_HEADER.match(line.rstrip("\r\n"))
        if match and match.group(2) == table:
            headers.append((index, match.group(1) == "[[" or match.group(3) == "]]"))
    if len(headers) > 1 or any(array for _, array in headers):
        return EditError(f"edit [{table}] by hand; its table structure is ambiguous")
    if not headers:
        inline = re.search(rf"^\s*{re.escape(table)}\s*=\s*\{{", text, re.MULTILINE)
        if inline:
            return EditError(f"edit [{table}] by hand; it is an inline table")
        separator = "" if not text or text.endswith("\n") else "\n"
        return f"{text}{separator}\n[{table}]\n{key} = {_literal(value)}\n"
    start = headers[0][0]
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if _TABLE_HEADER.match(lines[index].rstrip("\r\n")):
            end = index
            break
    matches = [
        index
        for index in range(start + 1, end)
        if (match := _ASSIGNMENT.match(lines[index].rstrip("\r\n")))
        and match.group(2) == key
    ]
    if len(matches) > 1:
        return EditError(f"edit [{table}].{key} by hand; duplicate keys were found")
    if matches:
        line_index = matches[0]
        old = lines[line_index]
        replacement = _replace_value(old.rstrip("\r\n"), key, value)
        if isinstance(replacement, EditError):
            return replacement
        ending = "\r\n" if old.endswith("\r\n") else "\n" if old.endswith("\n") else ""
        lines[line_index] = replacement + ending
    else:
        if end > start and not lines[end - 1].endswith(("\n", "\r")):
            lines[end - 1] += "\n"
        lines.insert(end, f"{key} = {_literal(value)}\n")
    return "".join(lines)


def _remove_fallback_tables(text: str, table: str) -> str:
    """Replace legacy array-of-table fallbacks with a writable inline array."""
    target = f"{table}.fallback"
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    skipping = False
    for line in lines:
        match = _TABLE_HEADER.match(line.rstrip("\r\n"))
        if match:
            is_array = match.group(1) == "[[" or match.group(3) == "]]"
            skipping = is_array and match.group(2) == target
        if not skipping:
            result.append(line)
    return "".join(result)


def apply(text: str, changes: dict[str, Any], registry: Any = None) -> str | EditError:
    errors = validate(changes, registry, text)
    if errors:
        message = "; ".join(f"{key}: {message}" for key, message in errors.items())
        return EditError(message)
    result = text
    for full_key, value in changes.items():
        table, key = full_key.rsplit(".", 1)
        if full_key.startswith("types.") and key == "fallback":
            result = _remove_fallback_tables(result, table)
        result = _edit_table(result, table, key, value)
        if isinstance(result, EditError):
            return result
    try:
        known = registry.known_harnesses() if registry is not None else None
        if known is None:
            parse_config(result)
        else:
            parse_config(result, known)
    except ConfigError:
        return EditError("edit refused because the resulting config is invalid")
    if registry is not None:
        try:
            role_config = parse_config(result, registry.known_harnesses())
            validate_guard_role(role_config.roles["guard"], registry)
        except ConfigError, AttributeError, KeyError, LookupError:
            return EditError("edit refused because the resulting config is invalid")
        if not _candidate_has_registered_choices(result, registry):
            return EditError("edit refused because the resulting config is invalid")
    return result
