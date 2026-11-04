"""Per-component attribution for a scored scope."""

from collections.abc import Sequence
from typing import Any

from ..calibration import Calibration
from ..fixedpoint import MICRO
from ..scoring import ScopeScore, rescore_without
from .fix_targets import (
    delegation_fix_targets,
    facts_by_function,
    file_fix_targets,
    fragmentation_fix_targets,
    function_fix_targets,
)

COMPONENTS = (
    "cognitive",
    "long_side",
    "small_side",
    "params",
    "names",
    "depth",
    "fan_out",
    "tree_size",
    "fragmentation",
    "file_size",
    "import_fan_out",
    "file_overhead",
    "module_fragmentation",
)

# Shadow-measure components: listed only when some file lost points to them.
MEASURE_COMPONENTS = ("nesting", "vague_names", "delegation")

HINTS = {
    "cognitive": "Simplify complex control flow and split distinct responsibilities.",
    "long_side": "Split long functions at cohesive responsibility boundaries.",
    "small_side": "Inline tiny single-purpose functions when they add indirection.",
    "params": "Group related parameters or simplify the function interface.",
    "names": "Replace vague or ambiguous names with specific names.",
    "depth": "Reduce long chains of project function calls.",
    "fan_out": "Reduce the number of distinct callees in a function.",
    "tree_size": "Reduce oversized call trees by removing unnecessary indirection.",
    "fragmentation": "Inline tiny single-caller helpers into their caller.",
    "file_size": "Split the file into cohesive modules.",
    "import_fan_out": "Reduce the file's dependency spread.",
    "file_overhead": "Reduce fixed per-file overhead by consolidating tiny files.",
    "module_fragmentation": "Inline tiny cross-file helpers into their caller.",
    "nesting": "Flatten deep nesting with guard clauses and early returns.",
    "vague_names": "Rename vague local names (data, tmp, ...) to say what they hold.",
    "delegation": "Inline one-call wrappers or give them a real responsibility.",
}
ATTRIBUTION_NOTE = "Recoverable points are per component and are not additive."

_FILE_COMPONENTS = {
    "fragmentation",
    "file_size",
    "import_fan_out",
    "file_overhead",
    "module_fragmentation",
    "delegation",
}


def breakdown(
    scope_score: ScopeScore,
    calibration: Calibration,
    records: Sequence[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Attribute debt and score loss to each component in deterministic order.

    ``records`` (the facts scored) adds token counts and name issues to each
    component's ``fix_targets``; without them size components list no targets.
    """
    facts = facts_by_function(records)
    names = _active_components(scope_score)
    totals = _component_totals(scope_score, names)
    shares = _shares(totals, scope_score.debt)
    lost_points = _points_lost(scope_score, names)
    return [
        {
            "name": name,
            "debt": totals[name],
            "share": shares[name],
            "points_lost": lost_points[name],
            "points_recoverable": _recoverable(scope_score, name),
            "attribution_note": ATTRIBUTION_NOTE,
            "worst_offenders": _offenders(scope_score, name),
            "hint": HINTS[name],
            "fix_targets": _fix_targets(scope_score, name, facts, calibration),
        }
        for name in names
    ]


def _active_components(scope_score: ScopeScore) -> tuple[str, ...]:
    """The base components plus any shadow-measure component with debt."""
    extra = tuple(
        name
        for name in MEASURE_COMPONENTS
        if any(file.components.get(name, 0) > 0 for file in scope_score.files)
    )
    return COMPONENTS + extra


def _fix_targets(
    scope_score: ScopeScore, component: str, facts: dict, calibration: Calibration
) -> list[dict[str, Any]]:
    if component == "fragmentation":
        return fragmentation_fix_targets(scope_score, facts, calibration)
    if component == "delegation":
        return delegation_fix_targets(scope_score, facts, calibration)
    if component in _FILE_COMPONENTS:
        return file_fix_targets(scope_score, component)
    return function_fix_targets(scope_score, component, facts)


def _component_totals(
    scope_score: ScopeScore, names: tuple[str, ...]
) -> dict[str, int]:
    totals: dict[str, int] = dict.fromkeys(names, 0)
    for file in scope_score.files:
        for name, debt in file.components.items():
            if name in totals:
                totals[name] += debt
    return totals


def _shares(totals: dict[str, int], total_debt: int) -> dict[str, int]:
    shares: dict[str, int] = (
        {name: debt * MICRO // total_debt for name, debt in totals.items()}
        if total_debt
        else dict.fromkeys(totals, 0)
    )
    if total_debt:
        remainder = MICRO - sum(shares.values())
        for name in sorted(
            totals, key=lambda key: (-(totals[key] * MICRO % total_debt), key)
        )[:remainder]:
            shares[name] += 1
    return shares


def _points_lost(scope_score: ScopeScore, names: tuple[str, ...]) -> dict[str, int]:
    lost: dict[str, int] = dict.fromkeys(names, 0)
    for file in scope_score.files:
        for name, points in (file.component_points_lost or {}).items():
            if name in lost:
                lost[name] += points
    return lost


def _recoverable(scope_score: ScopeScore, component: str) -> int:
    if scope_score.score is None:
        return 0
    rescored = rescore_without(scope_score, component)
    if rescored.score is None:
        return 0
    current = scope_score.score.numerator * MICRO // scope_score.score.denominator
    recovered = rescored.score.numerator * MICRO // rescored.score.denominator
    return max(0, recovered - current)


def _offenders(scope_score: ScopeScore, component: str) -> list[dict[str, Any]]:
    candidates = []
    for file in scope_score.files:
        component_debt = file.components.get(component, 0)
        if component_debt <= 0:
            continue
        if component in _FILE_COMPONENTS:
            candidates.append(_file_offender(file, component_debt))
            continue
        candidates.extend(
            _function_offender(function, component)
            for function in file.functions
            if function.costs.get(component, 0) > 0
        )
    return sorted(candidates, key=lambda item: (-item["debt"], item["id"]))[:5]


def _file_offender(file: Any, debt: int) -> dict[str, Any]:
    return {
        "id": file.path,
        "path": file.path,
        "line": None,
        "debt": debt,
        "value": None,
        "comfort": None,
    }


def _function_offender(function: Any, component: str) -> dict[str, Any]:
    return {
        "id": function.id,
        "path": function.path,
        "line": function.line,
        "debt": function.costs.get(component, 0),
        "value": function.value.get(component),
        "comfort": function.comfort.get(component),
    }


__all__ = ["ATTRIBUTION_NOTE", "COMPONENTS", "HINTS", "breakdown"]
