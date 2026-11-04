"""Implementation of the advisory execution-wave command."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from varde_learn.knowledge.memory_config import load_config

from varde_workflow.errors import CliError, report_error
from varde_workflow.execution_wave import WaveError, execution_wave
from varde_workflow.execution_wave_tools import git
from varde_workflow.output import print_cli_success


def run(args: Any, io: Any = None) -> int:
    plan = Path(args.plan_dir)
    root_value = getattr(args, "repo_root", None)
    root = Path(root_value) if root_value is not None else None
    if root is None:
        result = git(plan, ["rev-parse", "--show-toplevel"])
        if result is None or result[0] != 0 or not result[1].strip():
            return report_error(
                CliError("cannot discover repository root; pass --repo-root"), args.json
            )
        root = Path(result[1].strip())
    workers = getattr(args, "max_workers", None)
    if workers is None:
        try:
            values = load_config().orchestration.values
            value = values.get("builders", values.get("max_agents", 4))
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                workers = value
            else:
                workers = 4
                print(
                    (
                        "varde plan execution-wave: orchestration builders ignored "
                        f"({value!r} is not a positive integer); using {workers}"
                    ),
                    file=sys.stderr,
                )
        except ValueError as error:
            return report_error(
                CliError(f"could not load Varde config: {error}"), args.json
            )
    impact = getattr(io, "impact", None) if io is not None else None
    try:
        data = execution_wave(plan, root, workers, impact)
    except ValueError as error:
        return report_error(WaveError(str(error)), args.json)
    except WaveError as error:
        return report_error(error, args.json)
    if args.json:
        print_cli_success(data)
    else:
        print(json.dumps(data, indent=2, sort_keys=True))
    return 0
