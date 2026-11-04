# ruff: noqa: S101
import ast
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import quality_degrade as qd

AGREED = Path(__file__).resolve().parent.parent / "baseline/agreed"
SOURCES = {
    p.parent.parent.name: p.read_text() for p in AGREED.glob("*/python/solution.py")
}


def load(source: str, name: str):
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(source, name, "exec"), module.__dict__)  # noqa: S102
    return module


def job_scheduler(m):
    jobs = [m.Job("a", 2), m.Job("b", 1, 0, ("a",)), m.Job("c", 3, 2), m.Job("d", 1, 1)]
    return repr(m.run_jobs(jobs, 2))


def job_scheduler_cycle(m):
    try:
        m.run_jobs([m.Job("a", 1, 0, ("b",)), m.Job("b", 1, 0, ("a",))], 1)
    except ValueError as error:
        return str(error)
    return None


def report_pipeline(m):
    text = "k, v\na, 1.5\nb, 2\na, 3\n\n"
    return m.render_report(text, "k", "v")


def report_pipeline_error(m):
    try:
        m.render_report("k,v\na,nan\n", "k", "v")
    except ValueError as error:
        return str(error)
    return None


def notifier(m):
    seen = []
    dispatcher = m.Dispatcher(
        [("a", 1), ("b", 2)],
        lambda channel, text: seen.append(channel) or channel != "b",
    )
    return [dispatcher.dispatch("x", t) for t in (0, 1, 2, 70)], seen


def recurring_orders(m):
    system = m.OrderSystem()
    first = system.add_recurring("c", 100, 2, "2024-01-31")
    system.add_recurring("c", 50, 1, "2024-02-10")
    system.cancel(first + 5)
    early = system.orders_through("2024-03-31")
    system.cancel(first)
    return repr((early, system.orders_through("2024-06-30")))


SCENARIOS = {
    "job-scheduler": (job_scheduler, job_scheduler_cycle),
    "report-pipeline": (report_pipeline, report_pipeline_error),
    "notifier": (notifier,),
    "recurring-orders": (recurring_orders,),
}


def test_agreed_sources_are_present():
    assert set(SOURCES) == set(SCENARIOS)


@pytest.mark.parametrize("kind", [*qd.DEGRADATIONS, "identity"])
@pytest.mark.parametrize("problem", sorted(SCENARIOS))
def test_degradation_preserves_behaviour(problem, kind):
    degrade = qd.identity if kind == "identity" else qd.DEGRADATIONS[kind]
    original = load(SOURCES[problem], f"orig_{problem}")
    variant = load(degrade(SOURCES[problem]), f"{kind}_{problem}")
    for scenario in SCENARIOS[problem]:
        assert scenario(variant) == scenario(original)


def count_functions(source: str) -> int:
    return sum(isinstance(n, ast.FunctionDef) for n in ast.walk(ast.parse(source)))


def test_inline_removes_helpers_and_wrappers_add_functions():
    source = SOURCES["job-scheduler"]
    assert count_functions(qd.inline_helpers(source)) < count_functions(source)
    assert count_functions(qd.wrappers(source)) == 2 * count_functions(source) - 1
    assert count_functions(qd.deep_chain(source)) > count_functions(qd.wrappers(source))


def test_guard_inversion_moves_rest_into_else():
    src = "def f(x):\n    if x:\n        return 1\n    y = 2\n    return y\n"
    expected = "def f(x):\n    if x:\n        return 1\n    else:\n"
    expected += "        y = 2\n        return y\n"
    assert qd.guard_nesting(src) == expected


def test_rename_vague_uses_vague_locals_and_keeps_public_api():
    out = qd.rename_vague("def run(items, limit):\n    total = 0\n    return total\n")
    assert out == "def run(data, tmp):\n    val = 0\n    return val\n"


def test_add_params_appends_defaults():
    out = qd.add_params("def f(a):\n    return a\n")
    assert out.splitlines()[0] == "def f(a, flag=None, options=None, context=None):"


def test_degradations_are_deterministic():
    for degrade in qd.DEGRADATIONS.values():
        assert degrade(SOURCES["notifier"]) == degrade(SOURCES["notifier"])
