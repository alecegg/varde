from __future__ import annotations

import runpy
from pathlib import Path


def test_resource_budget_interim_gate_and_two_percent_target() -> None:
    script = Path(__file__).parents[1] / "scripts" / "check_resource_budget.py"
    checker = runpy.run_path(str(script))

    assert checker["IDLE_CPU_LIMIT_PERCENT"] == 10.0
    assert checker["IDLE_CPU_TARGET_PERCENT"] == 2.0
