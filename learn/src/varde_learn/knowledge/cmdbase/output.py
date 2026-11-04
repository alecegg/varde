"""Stable machine-readable output for command handlers."""

import json
import sys
from typing import Any, cast

from varde_core.envelope import negative_result, success, tool_error
from varde_core.jsonio import dumps


class Fix:
    """Fix guidance attached to a command failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    @classmethod
    def no_command(cls, reason: str) -> Fix:
        return cls(reason)

    def as_value(self) -> dict[str, str]:
        return {"reason": self.reason}

    def text(self) -> str:
        return self.reason


_FIX_RULES = {
    "review_invalid": (
        "Correct the review report or the merged commit named in the error, "
        "then rerun plan conclude."
    ),
    "unreadable_task": (
        "Correct the task or plan ownership metadata named in the error."
    ),
    "git_error": (
        "Repair Git input or restore the unavailable object described in the error."
    ),
    "internal": (
        "Inspect the reported failure and correct the unavailable input or state "
        "before retrying."
    ),
    "ownership_stray": (
        "Add each stray path to the task's `owns:` or the plan's `shared:`, then "
        "rerun check-task-ownership."
    ),
    "ownership_invalid": (
        "Correct invalid paths or ownership declarations, then rerun plan validate "
        "and check-task-ownership."
    ),
}


def for_code(code: str) -> Fix:
    return Fix.no_command(
        _FIX_RULES.get(code, f"no fix guidance is registered for error code `{code}`")
    )


def page_bounds(total: int, offset: int, limit: int, all: bool) -> tuple[int, int]:
    start = min(offset, total)
    return start, total if all else min(start + limit, total)


def pagination_meta(
    total: int, start: int, end: int, limit: int, all: bool
) -> dict[str, Any]:
    truncated = end < total
    return {
        "truncated": truncated,
        "pagination": {
            "total": total,
            "returned": max(0, end - start),
            "offset": start,
            "limit": None if all else limit,
            "truncated": truncated,
            "next_offset": end if truncated else None,
        },
    }


def print_success(data: object) -> None:
    print_success_with_meta(data, {"truncated": False})


def print_success_with_meta(data: object, meta: object) -> None:
    print(dumps(success(data, meta)))


def print_error(code: str, message: str) -> None:
    import sys

    print(dumps(tool_error(code, message)), file=sys.stderr)


def print_error_with_fix(code: str, message: str, fix: Fix) -> None:
    import sys

    envelope = tool_error(code, message)
    data = cast("dict[str, Any]", envelope["data"])
    cast("dict[str, Any]", data["error"])["fix"] = fix.as_value()
    print(dumps(envelope), file=sys.stderr)


def print_failure(code: str, message: str, details: object) -> None:
    details, fix = _take_fix(details)
    envelope = negative_result(code, message, details, {"truncated": False})
    if fix is not None:
        data = cast("dict[str, Any]", envelope["data"])
        cast("dict[str, Any]", data["error"])["fix"] = fix
    print(dumps(envelope))


def print_failure_with_meta(
    code: str, message: str, details: object, meta: object
) -> None:
    print(dumps(negative_result(code, message, details, meta)))


def print_failure_with_fix(code: str, message: str, details: object, fix: Fix) -> None:
    details, embedded_fix = _take_fix(details)
    envelope = negative_result(code, message, details, {"truncated": False})
    data = cast("dict[str, Any]", envelope["data"])
    cast("dict[str, Any]", data["error"])["fix"] = embedded_fix or fix.as_value()
    print(dumps(envelope))


def print_cli_success(data: object) -> None:
    """Print a Rust CLI compatible success envelope with sorted JSON keys."""
    print_cli_success_with_meta(data, {"truncated": False})


def print_cli_success_with_meta(data: object, meta: object) -> None:
    _print_cli_json(success(data, meta))


def print_cli_failure_with_meta(
    code: str, message: str, details: object, meta: object
) -> None:
    _print_cli_json(negative_result(code, message, details, meta))


def print_cli_tool_error(code: str, message: str) -> None:
    _print_cli_json(tool_error(code, message), file=sys.stderr)


def _print_cli_json(value: object, *, file=None) -> None:
    print(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        file=file,
    )


def _take_fix(details: object) -> tuple[object, object | None]:
    if not isinstance(details, dict):
        return details, None
    details = dict(details)
    fix = details.pop("fix", None)
    if fix is None:
        blockers = details.get("blockers")
        if isinstance(blockers, list) and blockers and isinstance(blockers[0], dict):
            fix = blockers[0].get("fix")
    return details, fix
