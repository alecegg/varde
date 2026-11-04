"""Per-category fix targets: the worst functions (or files) behind a loss."""

from collections.abc import Sequence
from typing import Any

from ..costs import CostParameters
from ..fixedpoint import MICRO

TOP = 3
OVER = {"cognitive", "long_side", "params", "depth", "fan_out", "tree_size"}
UNDER = {"small_side"}
TOKEN_COMPONENTS = {"long_side", "small_side"}
FACTS_KEY = "name_issues"


def facts_by_function(
    records: Sequence[dict[str, Any]] | None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Index facts functions by (path, id); empty when no records are given."""
    return {
        (str(record.get("path", "")), str(function.get("id", ""))): function
        for record in records or ()
        for function in record.get("functions", ())
    }


def function_fix_targets(
    scope_score: Any,
    component: str,
    facts: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Top functions beyond the comfort target, with their share of the loss."""
    rows = [
        (function, facts.get((function.path, function.id), {}))
        for file in scope_score.files
        for function in file.functions
        if function.costs.get(component, 0) > 0
    ]
    total = sum(function.costs[component] for function, _ in rows)
    targets = [
        _function_target(function, fn_facts, component, total)
        for function, fn_facts in rows
    ]
    beyond = [t for t in targets if _beyond_comfort(component, t["now"], t["target"])]
    limited = [t for t in targets if _has_limit(t)]
    chosen = beyond or [_within(t, len(limited)) for t in limited]
    return sorted(chosen, key=lambda t: (-t["share"], t["id"]))[:TOP]


def file_fix_targets(scope_score: Any, component: str) -> list[dict[str, Any]]:
    """Top files behind a file-level component loss."""
    rows = [
        (file.path, file.components.get(component, 0))
        for file in scope_score.files
        if file.components.get(component, 0) > 0
    ]
    total = sum(debt for _, debt in rows)
    targets = [
        {
            "id": path,
            "path": path,
            "line": None,
            "share": debt * MICRO // total,
            "now": None,
            "target": None,
        }
        for path, debt in rows
    ]
    return sorted(targets, key=lambda t: (-t["share"], t["id"]))[:TOP]


def fragmentation_fix_targets(
    scope_score: Any,
    facts: dict[tuple[str, str], dict[str, Any]],
    calibration: Any,
) -> list[dict[str, Any]]:
    """Tiny single-caller helpers behind fragmentation; file-level if unknown."""
    helpers = []
    for file in scope_score.files:
        if file.components.get("fragmentation", 0) <= 0:
            continue
        limits = _fragment_limits(calibration, file.language)
        if limits is None or not facts:
            return file_fix_targets(scope_score, "fragmentation")
        helpers += _tiny_helpers(file.path, facts, *limits)
    targets = [{**helper, "share": MICRO // len(helpers)} for helper in helpers]
    return sorted(targets, key=lambda t: (t["tokens"], t["id"]))[:TOP]


def delegation_fix_targets(
    scope_score: Any,
    facts: dict[tuple[str, str], dict[str, Any]],
    calibration: Any,
) -> list[dict[str, Any]]:
    """One-call wrappers in files that lost points to delegation."""
    wrappers = []
    for file in scope_score.files:
        if file.components.get("delegation", 0) <= 0:
            continue
        flagged = [
            (function_id, fn)
            for (path, function_id), fn in facts.items()
            if path == file.path
            and fn.get("delegates") is not None
            and not fn.get("exempt_role")
        ]
        if not flagged:
            return file_fix_targets(scope_score, "delegation")
        allowed = _tolerated_wrappers(calibration, file.language, len(flagged))
        wrappers += [
            _wrapper_target(function_id, file.path, fn, allowed, flagged)
            for function_id, fn in flagged
            if fn["delegates"]
        ]
    targets = [{**w, "share": MICRO // len(wrappers)} for w in wrappers]
    return sorted(targets, key=lambda t: (t["tokens"] or 0, t["id"]))[:TOP]


def _tolerated_wrappers(calibration: Any, language: str, flagged: int) -> int:
    """Whole wrappers allowed by the ``dg0`` share for ``flagged`` functions."""
    entry = getattr(calibration, "languages", {}).get(language)
    share = getattr(entry, "parameters", {}).get("dg0", CostParameters.dg0)
    return share * flagged // MICRO


def _wrapper_target(
    function_id: str,
    path: str,
    fn: dict[str, Any],
    allowed: int,
    flagged: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "id": function_id,
        "path": path,
        "line": fn.get("line"),
        "now": sum(1 for _, other in flagged if other["delegates"]),
        "target": allowed,
        "tokens": fn.get("tokens"),
    }


def _fragment_limits(calibration: Any, language: str) -> tuple[int, int] | None:
    """(tiny-helper token limit, tolerated count) in whole units, if calibrated."""
    parameters = getattr(calibration, "languages", {}).get(language)
    values = getattr(parameters, "parameters", {})
    if "t_frag" not in values:
        return None
    allowed = values.get("cF0", CostParameters.cF0 * MICRO)
    return values["t_frag"] // MICRO, allowed // MICRO


def _tiny_helpers(
    path: str, facts: dict[tuple[str, str], dict[str, Any]], tiny: int, allowed: int
) -> list[dict[str, Any]]:
    found = [
        (function_id, fn)
        for (fn_path, function_id), fn in facts.items()
        if fn_path == path
        and fn.get("fragment_scope") == "file"
        and (fn.get("tokens") or 0) <= tiny
        and not fn.get("exempt_role")
    ]
    return [
        {
            "id": function_id,
            "path": path,
            "line": fn.get("line"),
            "now": len(found),
            "target": allowed,
            "tokens": fn.get("tokens"),
        }
        for function_id, fn in found
    ]


def _function_target(
    function: Any, facts: dict[str, Any], component: str, total: int
) -> dict[str, Any]:
    issues: list[str] = sorted(set(facts.get(FACTS_KEY) or ()))
    return {
        "id": function.id,
        "path": function.path,
        "line": function.line,
        "share": function.costs[component] * MICRO // total,
        "now": _now(function, facts, issues, component),
        "target": 0 if component == "names" else function.comfort.get(component),
        "tokens": facts.get("tokens"),
        "complexity": function.value.get("cognitive"),
        "issues": issues,
    }


def _has_limit(target: dict[str, Any]) -> bool:
    return target["now"] is not None and target["target"] is not None


def _within(target: dict[str, Any], spread: int) -> dict[str, Any]:
    return {**target, "within_limit": True, "spread": spread}


def _now(function: Any, facts: dict[str, Any], issues: list[str], component: str):
    if component in TOKEN_COMPONENTS:
        return facts.get("tokens")
    if component == "names":
        return len(issues)
    return function.value.get(component)


def _beyond_comfort(component: str, now: int | None, target: int | None) -> bool:
    if now is None or target is None:
        return False
    if component in UNDER:
        return now < target
    return now > target
