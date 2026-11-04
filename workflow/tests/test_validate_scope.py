from __future__ import annotations

from pathlib import Path

import pytest
from varde_workflow import cli

PLAN = (
    "---\ntype: plan\nstatus: active\nlabel: Scope Plan\ngroup: Tests\n{scope}---\n"
    "## Acceptance criteria\n- valid\n"
)
TASK = (
    "---\ntype: task\nstatus: todo\ndepends_on: {deps}\nowns: []\n---\n"
    "## Acceptance criteria\n- done\n"
)


def _plan(tmp_path: Path, scope: str, chain: bool = True) -> Path:
    (tmp_path / "tasks").mkdir()
    plan = tmp_path / "plan.md"
    plan.write_text(PLAN.format(scope=scope), encoding="utf-8")
    (tmp_path / "tasks" / "a.md").write_text(TASK.format(deps="[]"), encoding="utf-8")
    deps = "[a]" if chain else "[]"
    (tmp_path / "tasks" / "b.md").write_text(TASK.format(deps=deps), encoding="utf-8")
    return plan


def test_valid_serial_plan_with_scope(tmp_path: Path) -> None:
    plan = _plan(tmp_path, 'scope: ["src/**"]\n')
    assert cli.run(["plan", "validate", str(plan)]) == 0


@pytest.mark.parametrize("scope", ["scope: src\n", 'scope: [""]\n', "scope: [1]\n"])
def test_invalid_scope_value(tmp_path: Path, scope: str) -> None:
    plan = _plan(tmp_path, scope)
    assert cli.run(["plan", "validate", str(plan)]) != 0


def test_scope_on_non_serial_plan(tmp_path: Path) -> None:
    plan = _plan(tmp_path, 'scope: ["src/**"]\n', chain=False)
    assert cli.run(["plan", "validate", str(plan)]) != 0


def test_scope_on_plan_without_tasks_is_valid(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(PLAN.format(scope='scope: ["src/**"]\n'), encoding="utf-8")
    assert cli.run(["plan", "validate", str(plan)]) == 0
