"""Shared validation helpers for query mode inputs."""

from __future__ import annotations

from typing import Any


class QueryError(ValueError):
    """A query input or execution error with a stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def object_input(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise QueryError("invalid_input", "input must be a JSON object")
    return value


def req_str(value: dict[str, Any], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str):
        raise QueryError("invalid_input", f'missing string field "{field}"')
    return result


def opt_str(value: dict[str, Any], field: str) -> str | None:
    result = value.get(field)
    return result if isinstance(result, str) else None


def nonnegative_int(
    value: dict[str, Any], field: str, default: int | None = None
) -> int | None:
    if field not in value:
        return default
    result = value[field]
    if isinstance(result, bool) or not isinstance(result, int) or result < 0:
        raise QueryError("invalid_input", f"{field} must be a nonnegative integer")
    return result
