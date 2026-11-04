"""Command line interface for ``varde learn run``."""

from __future__ import annotations

import json
import sys

from varde_core.envelope import negative_result, success

from .help import help_text
from .review.redact import redact


def run(argv: list[str], io: object | None = None) -> int:
    args = list(argv)
    if args and args[0] == "run":
        args.pop(0)
    stream = getattr(io, "stdout", sys.stdout) if io else sys.stdout
    if "--help" in args or "-h" in args:
        stream.write(help_text("run"))
        return 0
    json_output = "--json" in args
    try:
        window, budget_tokens, no_model, dry_run = _parse_options(args)
        from .review.run import run_review

        result = run_review(
            window=window,
            budget_tokens=budget_tokens,
            no_model=no_model,
            dry_run=dry_run,
        )
        if json_output:
            stream.write(
                json.dumps(success(result, {"truncated": False}), separators=(",", ":"))
                + "\n"
            )
        else:
            coverage = result["coverage"]
            stream.write(
                f"Review: {coverage['analyzed']} analyzed, "
                f"{coverage['skipped']} skipped, {coverage['failed']} failed, "
                f"{coverage['pending']} pending.\n"
            )
    except Exception as error:  # noqa: BLE001 - CLI failures share one boundary
        error_stream = getattr(io, "stderr", sys.stderr) if io else sys.stderr
        if json_output:
            stream.write(
                json.dumps(
                    negative_result(
                        "learn_run_failed",
                        redact(str(error)),
                        None,
                        {"truncated": False},
                    ),
                    separators=(",", ":"),
                )
                + "\n"
            )
        else:
            error_stream.write(f"error: {redact(str(error))}\n")
        return 2
    return 0


def _parse_options(args: list[str]) -> tuple[str, int | None, bool, bool]:
    window = "yesterday"
    budget_tokens = None
    no_model = False
    dry_run = False
    index = 0
    while index < len(args):
        value = args[index]
        if value.startswith("--window="):
            window = value.partition("=")[2]
        elif value.startswith("--budget-tokens="):
            budget_tokens = _positive_budget(value.partition("=")[2])
        elif value == "--no-model":
            no_model = True
        elif value == "--dry-run":
            dry_run = True
        elif value == "--json":
            pass
        elif value in {"--window", "--budget-tokens"}:
            index += 1
            if index >= len(args):
                _invalid_argument(f"{value} requires a value")
            if value == "--window":
                window = args[index]
            else:
                budget_tokens = _positive_budget(args[index])
        else:
            _invalid_argument(f"unexpected argument '{value}'")
        index += 1
    return window, budget_tokens, no_model, dry_run


def _invalid_argument(message: str) -> None:
    raise ValueError(message)


def _positive_budget(value: str) -> int:
    try:
        budget = int(value)
    except ValueError as error:
        raise ValueError("--budget-tokens must be a positive integer") from error
    if budget < 1:
        _invalid_argument("--budget-tokens must be positive")
    return budget
