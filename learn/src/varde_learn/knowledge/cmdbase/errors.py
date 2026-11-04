"""Shared command error codes and reporting."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from .output import for_code, print_error, print_error_with_fix

T = TypeVar("T")


class ExitCode:
    """Base behavior for errors reported by command handlers."""

    def exit_code(self) -> int:
        return 1

    def error_code(self) -> str:
        return "internal"


@dataclass
class CliError(Exception, ExitCode):
    message: str

    def __str__(self) -> str:
        return self.message

    def error_code(self) -> str:
        return "invalid_input"


@dataclass
class InternalError(Exception, ExitCode):
    message: str

    def __str__(self) -> str:
        return self.message


def report_error(err: Exception, json: bool) -> int:
    code = err.error_code() if isinstance(err, ExitCode) else "internal"
    exit_code = err.exit_code() if isinstance(err, ExitCode) else 1
    if json:
        print_error_with_fix(code, str(err), for_code(code)) if isinstance(
            err, InternalError
        ) else print_error(code, str(err))
    else:
        import sys

        suffix = (
            f"\nFix: {for_code(code).text()}" if isinstance(err, InternalError) else ""
        )
        print(f"error: {err}{suffix}", file=sys.stderr)
    return exit_code


def report_cli_error(err: Exception, json: bool) -> int:
    """Report command errors using the Rust CLI envelope and exit contract."""
    code = err.error_code() if isinstance(err, ExitCode) else "internal"
    exit_code = err.exit_code() if isinstance(err, ExitCode) else 1
    if json:
        from .output import print_cli_tool_error

        print_cli_tool_error(code, str(err))
    else:
        import sys

        print(f"error: {err}", file=sys.stderr)
    return exit_code


def finish[T](
    result: tuple[bool, T | Exception],
    json: bool,
    render_json: Callable[[T], None],
    render_text: Callable[[T], None],
) -> int | None:
    ok, value = result
    if not ok:
        if not isinstance(value, Exception):
            raise AssertionError("failed result must contain an exception")
        return report_error(value, json)
    (render_json if json else render_text)(value)  # type: ignore[arg-type]
    return None
