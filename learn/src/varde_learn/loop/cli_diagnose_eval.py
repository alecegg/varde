"""Eval command parsing and dispatch for the learn CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from varde_core.envelope import success

from .cli_diagnose import (
    _error,
    _parse_error,
    _ParseFailure,
    _Parser,
    _print_json,
    help_text,
)

_SPECS = {
    "trigger": {
        "harness": ("text", True),
        "runs": ("int", True),
        "timeout_seconds": ("int", True),
        "skill_path": ("text", True),
        "split": ("text", True),
        "skill_name": ("positional", False),
        "queries": ("positional", False),
    },
    "output": {
        "harness": ("text", True),
        "model": ("text", True),
        "judge_model": ("text", True),
        "runs": ("int", True),
        "iteration": ("int", True),
        "workspace": ("text", True),
        "eval": ("text", True),
        "timeout_seconds": ("int", True),
        "sandbox_dir": ("text", True),
        "no_baseline": ("flag", False),
        "skill_dir": ("positional", False),
    },
    "calibrate": {
        "harness": ("text", True),
        "json": ("flag", False),
        "skill_dir": ("positional", False),
    },
}


def run_eval(args: list[str]) -> int:
    if not args:
        print(help_text("eval"), end="")
        return 0
    command = args.pop(0)
    if command not in _SPECS:
        return _parse_error(f"unexpected argument '{command}'", "--json" in args)
    options: dict[str, Any] = {}
    try:
        options = _Parser(f"eval {command}", _SPECS[command]).parse(args)
        if command == "trigger":
            return _run_trigger(options)
        if command == "output":
            return _run_output(options)
        return _run_calibrate(options)
    except SystemExit as error:
        return int(error.code or 0)
    except _ParseFailure as error:
        return _parse_error(str(error), "--json" in args)
    except Exception as error:
        default_code = (
            "usage_error" if command in {"output", "calibrate"} else "eval_error"
        )
        return _error(
            getattr(error, "code", default_code),
            str(error),
            2,
            json_requested=bool(options.get("json")),
        )


def _run_trigger(options: dict[str, Any]) -> int:
    from .trigger import CLAUDE, CODEX, OPENCODE, TriggerRequest, run_trigger

    if options.get("harness") not in {"claude", "codex", "opencode"}:
        raise ValueError("--harness must be claude, codex, or opencode")
    if not options.get("skill_name") or not options.get("queries"):
        raise ValueError("skill name and queries file are required")
    harness = {"claude": CLAUDE, "codex": CODEX, "opencode": OPENCODE}[
        options["harness"]
    ]
    report = run_trigger(
        TriggerRequest(
            options["skill_name"],
            Path(options["queries"]),
            harness,
            int(options.get("runs", 3)),
            int(options.get("timeout_seconds", 300)),
            Path(options["skill_path"]) if options.get("skill_path") else None,
            options.get("split", "all"),
        )
    )
    for line in report.fail_lines:
        print(line)
    print(report.summary_line)
    return int(report.failed)


def _output_context(options: dict[str, Any]):
    from .output.command import OutputHarness

    harness_name = options.get("harness", "codex")
    if harness_name not in {"codex", "claude"}:
        raise ValueError("--harness must be codex or claude")
    if not options.get("skill_dir"):
        raise ValueError(
            "the following required arguments were not provided: <SKILL_DIR>"
        )
    return OutputHarness(harness_name), Path(options["skill_dir"])


def _run_output(options: dict[str, Any]) -> int:
    from .output.command import OutputRequest, run_output

    harness, skill_dir = _output_context(options)
    report = run_output(
        OutputRequest(
            skill_dir=skill_dir,
            harness=harness,
            model=options.get("model"),
            judge_model=options.get("judge_model"),
            runs=int(options.get("runs", 1)),
            iteration=int(options.get("iteration", 1)),
            workspace=Path(options["workspace"]) if options.get("workspace") else None,
            eval_ids=tuple(options.get("eval", ())),
            timeout_seconds=int(options.get("timeout_seconds", 300)),
            sandbox_dir=Path(options["sandbox_dir"])
            if options.get("sandbox_dir")
            else None,
            no_baseline=bool(options.get("no_baseline")),
        )
    )
    for record in report.records:
        print(
            (  # noqa: UP034 - keep the wrapped output explicitly grouped
                f"{record.eval_id} {record.config.value} run-{record.run}: "
                f"{record.outcome.value}"
            )
        )
    if report.excluded_ids:
        print(f"excluded evals: {', '.join(report.excluded_ids)}")
    print(f"eval output: {len(report.records)} runs written to {report.iteration_dir}")
    print(f"benchmark -> {report.iteration_dir / 'benchmark.json'}")
    return 0


def _run_calibrate(options: dict[str, Any]) -> int:
    from .output.command import calibrate

    harness, skill_dir = _output_context(options)
    report = calibrate(skill_dir, harness)
    if options.get("json"):
        _print_json(success(report, {"command": "eval calibrate"}))
    else:
        print(f"calibration {'passed' if report['passed'] else 'failed'}")
    return 0 if report["passed"] else 1
