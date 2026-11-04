"""CLI adapter for the deterministic task gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from varde_workflow.plan_gate import GateResult, evaluate


def run(args: Any) -> int:
    try:
        task = Path(args.task)
        repo_root = getattr(args, "repo_root", None)
        results, failed = evaluate(
            task,
            getattr(args, "commit", None),
            Path(repo_root) if repo_root is not None else None,
        )
    except (OSError, ValueError) as error:
        results, failed = [GateResult("preflight", "fail", str(error))], True
    failure_number = 0
    for result in results:
        detail = result.detail.replace("\n", " ").replace(",", ";")
        print(f"{result.check}, {result.status}, {detail}")
        if result.status == "fail":
            failure_number += 1
            print(f"GATE-{failure_number:03d} high: {result.check}: {detail}")
            if result.fix:
                print(f"Fix: {result.fix}")
    return 1 if failed else 0


def help_text() -> str:
    return (Path(__file__).parents[1] / "help" / "plan_gate.txt").read_text(
        encoding="utf-8"
    )
