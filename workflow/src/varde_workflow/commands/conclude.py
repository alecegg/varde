"""CLI adapter for plan conclusion."""

from __future__ import annotations

import json
import sys
from typing import Any, cast

from varde_core.envelope import tool_error
from varde_learn.knowledge.cmdbase.output import for_code

from varde_workflow.commands.error import ExitCode
from varde_workflow.commands.plan_write_errors import (
    PLAN_CONFLICT_CODE,
    PLAN_LOCKED_CODE,
)
from varde_workflow.conclusion import conclude
from varde_workflow.errors import InternalError, error_fix
from varde_workflow.output import print_cli_success


def run(args: Any) -> int:
    try:
        result = conclude(
            args.plan, getattr(args, "merged", None), getattr(args, "repo", None)
        )
    except (OSError, ValueError) as exc:
        error = exc if isinstance(exc, ExitCode) else InternalError(str(exc))
        if getattr(args, "json", False):
            code = error.error_code()
            envelope = tool_error(code, str(exc))
            data = cast("dict[str, Any]", envelope["data"])
            fix = (
                {"reason": error_fix(code)}
                if code in {PLAN_CONFLICT_CODE, PLAN_LOCKED_CODE}
                else for_code(code).as_value()
            )
            cast("dict[str, Any]", data["error"])["fix"] = fix
            print(
                json.dumps(
                    envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ),
                file=sys.stderr,
            )
        else:
            print(
                f"error: {exc}\nFix: {error_fix(error.error_code())}", file=sys.stderr
            )
        return error.exit_code()
    if getattr(args, "json", False):
        print_cli_success({"plan_id": result.id, "reviewed_head": result.head})
    else:
        print(f"concluded {result.id}")
    return 0
