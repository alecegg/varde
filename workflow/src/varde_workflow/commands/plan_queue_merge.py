"""Run explicit reversible role-inbox queue migrations."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from varde_data.errors import DataError
from varde_data.role_queue_merge import merge_role_queue, rollback_role_queue
from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.errors import InternalError, report_error
from varde_workflow.output import print_cli_success


def run(args: Any) -> int:
    """Merge queue tables into the inbox DB or restore the legacy queue DB."""
    working = MemoryPaths.resolve(Path.cwd()).working.path
    try:
        operation = (
            merge_role_queue
            if args.queue_action == "merge-role-inbox"
            else rollback_role_queue
        )
        report = operation(working)
    except (DataError, OSError, ValueError, sqlite3.Error) as error:
        return report_error(InternalError(str(error)), bool(args.json))
    payload = asdict(report)
    if payload["backup"] is not None:
        payload["backup"] = str(payload["backup"])
    print_cli_success(payload)
    return 0
