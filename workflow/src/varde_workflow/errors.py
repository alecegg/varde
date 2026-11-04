"""Shared command errors and workflow-specific reporting helpers."""

import json
import sys
from typing import Any, cast

from varde_core.envelope import negative_result, tool_error
from varde_learn.knowledge.cmdbase.errors import (
    CliError,
    ExitCode,
    InternalError,
    finish,
    report_cli_error,
)
from varde_learn.knowledge.cmdbase.output import Fix, print_cli_tool_error

_ERROR_FIXES = {
    "internal": (
        "Inspect the reported failure and correct the unavailable input or state "
        "before retrying."
    ),
    "git_error": (
        "Repair Git input or restore the unavailable object described in the error."
    ),
    "review_invalid": (
        "Correct the review report or the merged commit named in the error, then "
        "rerun plan conclude."
    ),
    "plan_conflict": "Reload the plan to review the hand edit, then retry the command.",
    "plan_locked": "Retry the command after the other plan operation finishes.",
}


def error_fix(code: str) -> str:
    """Return the user-facing fix text for a workflow error code."""
    return _ERROR_FIXES.get(code, _ERROR_FIXES["internal"])


def _print_cli_error(code: str, message: str, fix: Fix | None = None) -> None:
    if fix is None and code not in _ERROR_FIXES:
        print_cli_tool_error(code, message)
        return
    envelope = tool_error(code, message)
    reason = fix.reason if fix else _ERROR_FIXES[code]
    data = cast("dict[str, Any]", envelope["data"])
    cast("dict[str, Any]", data["error"])["fix"] = {"reason": reason}
    print(
        json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        file=sys.stderr,
    )


def report_error(err: Exception, json_output: bool) -> int:
    code = err.error_code() if isinstance(err, ExitCode) else "internal"
    exit_code = err.exit_code() if isinstance(err, ExitCode) else 1
    if json_output:
        _print_cli_error(code, str(err))
    else:
        suffix = f"\nFix: {_ERROR_FIXES.get(code, _ERROR_FIXES['internal'])}"
        print(f"Error: {err}{suffix}", file=sys.stderr)
    return exit_code


def report_error_with_fix(
    code: str, exit_code: int, message: str, fix: Fix, json_output: bool
) -> int:
    """Report an error with workflow fix guidance and return its exit status."""
    if json_output:
        _print_cli_error(code, message, fix)
    else:
        import sys

        print(f"Error: {message}\nFix: {fix.text()}", file=sys.stderr)
    return exit_code


def report_failure_with_fix(
    code: str,
    exit_code: int,
    message: str,
    details: object,
    fix: Fix,
    json_output: bool,
) -> int:
    """Report a structured failure with workflow fix guidance."""
    if json_output:
        envelope = negative_result(code, message, details, {"truncated": False})
        data = cast("dict[str, Any]", envelope["data"])
        cast("dict[str, Any]", data["error"])["fix"] = fix.as_value()
        print(
            json.dumps(
                envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
        )
    else:
        import sys

        print(f"Error: {message}\nFix: {fix.text()}", file=sys.stderr)
    return exit_code


__all__ = [
    "CliError",
    "ExitCode",
    "Fix",
    "InternalError",
    "error_fix",
    "finish",
    "report_cli_error",
    "report_error",
    "report_error_with_fix",
    "report_failure_with_fix",
]
