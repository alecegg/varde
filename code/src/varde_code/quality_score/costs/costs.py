"""Deterministic fixed-point quality cost functions."""

from dataclasses import dataclass
from typing import Any

from ..fixedpoint import MICRO


@dataclass(frozen=True)
class CostParameters:
    """Calibration values; strengths and measurements use micro-units where noted."""

    A: int = 2 * MICRO
    w: int = MICRO
    wL: int = 600_000
    lam: int = 300_000
    Plo: int = 32
    Phi: int = 96
    c0: int = 10
    cs: int = 29
    ss: int = 170
    p0: int = 3
    ps: int = 4
    F0: int = 1000
    Fs: int = 1000
    o0: int = 2
    os: int = 4
    cmin: int = 3
    t_frag: int = 60
    cF0: int = 3
    cFs: int = 6
    dp0: int = 3
    dps: int = 2
    k0: int = 4
    ks: int = 6
    t0: int = 6
    ts: int = 8
    H: int = 6
    kappa_F: int = 0
    n0: int = 1
    nm0: int = 0
    dg0: int = MICRO // 3
    sn: int = 0
    sm: int = 0
    sd: int = 0
    name_unit: int = MICRO // 10
    name_cap: int = 150_000
    data_function_cap: int = 1_000_000
    component_caps: tuple[tuple[str, int], ...] = ()


def function_costs(
    function: dict[str, Any],
    params: CostParameters,
    *,
    file_record: dict[str, Any] | None = None,
    data_functions: list[str] | None = None,
) -> dict[str, int]:
    """Compute intrinsic costs for one facts function; all costs are micro-units."""
    file_record = file_record or {}
    if function_is_unmeasured(function, file_record):
        return {}
    tokens = max(0, function.get("tokens") or 0)
    structure_measured = file_record.get("structure_confidence") != "low"
    costs = {
        "cognitive": _quadratic_excess(
            function.get("cognitive") or 0, params.c0, params.cs, params.w
        )
        + _linear(function.get("cognitive") or 0, params.cs, params.lam),
        "long_side": _quadratic_excess(tokens, params.Phi, params.ss, params.wL)
        + _linear(tokens, params.ss, params.lam),
        "small_side": _quadratic_shortfall(tokens, params.Plo, params.A)
        if not function.get("exempt_role")
        else 0,
        "params": _linear(
            max(0, (function.get("params") or 0) - params.p0), params.ps, MICRO
        ),
        "names": _name_cost(function.get("name_issues", ()), params),
        "depth": _quadratic_excess(
            min(function["depth"], params.H), params.dp0, params.dps, MICRO
        )
        if structure_measured and function.get("depth") is not None
        else 0,
        "fan_out": _quadratic_excess(function["fan_out"], params.k0, params.ks, MICRO)
        if structure_measured and function.get("fan_out") is not None
        else 0,
        "tree_size": _quadratic_excess(
            function["tree_size"], params.t0, params.ts, MICRO
        )
        if structure_measured and function.get("tree_size") is not None
        else 0,
    }
    data_function_ids = (
        file_record.get("data_functions", ())
        if data_functions is None
        else data_functions
    )
    costs.update(_measure_costs(function, params))
    if function.get("id") in data_function_ids:
        total = sum(costs.values())
        if total > params.data_function_cap:
            costs = {
                key: value * params.data_function_cap // total
                for key, value in costs.items()
            }
    return _apply_caps(costs, params.component_caps)


def dominance_scale(function_tokens: int, file_tokens: int, strength: int) -> int:
    """Micro-unit multiplier of a function's costs by its share of the file.

    A function holding at most half of the file's tokens scales by 1; one holding
    all of them scales by ``1 + strength``. Zero strength is the identity.
    """
    if strength <= 0 or file_tokens <= 0:
        return MICRO
    excess = max(0, 2 * function_tokens - file_tokens)
    return MICRO + strength * excess // file_tokens


def file_costs(record: dict[str, Any], params: CostParameters) -> dict[str, int]:
    """Compute file-level costs, including same-file fragmentation and overhead."""
    functions = unique_functions(record.get("functions", ()))
    fragments = sum(
        1
        for fn in functions
        if fn.get("fragment_scope") == "file"
        and (fn.get("tokens") or 0) <= params.t_frag
        and not fn.get("exempt_role")
        and record.get("structure_confidence") != "low"
        and not function_is_unmeasured(fn, record)
    )
    tokens = max(0, record.get("tokens") or 0)
    parity = record.get("comment_parity") or {"tokens": tokens, "comment_tokens": 0}
    _measured_tokens = max(
        0, (parity.get("tokens", tokens) or 0) - (parity.get("comment_tokens", 0) or 0)
    )
    costs = {
        "fragmentation": _quadratic_excess(fragments, params.cF0, params.cFs, MICRO),
        "file_size": _quadratic_excess(
            record.get("tokens") or 0, params.F0, params.Fs, MICRO
        ),
        "import_fan_out": _quadratic_excess(
            record["import_fan_out"], params.o0, params.os, MICRO
        )
        if record.get("import_fan_out") is not None
        else 0,
        "file_overhead": params.kappa_F,
    }
    costs.update(_delegation_cost(functions, params))
    return _apply_caps(costs, params.component_caps)


def module_fragmentation_cost(
    records: list[dict[str, Any]], params: CostParameters
) -> int:
    """Return one module fragmentation cost across its supplied file records."""
    fragments = sum(
        1
        for record in records
        for function in unique_functions(record.get("functions", ()))
        if function.get("fragment_scope") == "module"
        and (function.get("tokens") or 0) <= params.t_frag
        and not function.get("exempt_role")
        and record.get("structure_confidence") != "low"
        and not function_is_unmeasured(function, record)
    )
    cost = _quadratic_excess(fragments, params.cF0, params.cFs, MICRO)
    return _apply_caps({"module_fragmentation": cost}, params.component_caps)[
        "module_fragmentation"
    ]


def function_is_unmeasured(
    function: dict[str, Any], file_record: dict[str, Any] | None = None
) -> bool:
    """Return whether the function span intersects a file's unmeasured region."""
    start, end = function.get("line"), function.get("end_line", function.get("line"))
    if start is None or end is None:
        return False
    return any(
        start <= region.get("end_line", -1) and end >= region.get("start_line", 1)
        for region in (file_record or {}).get("unmeasured_regions", ())
    )


def function_coverage(
    functions: list[dict[str, Any]], file_record: dict[str, Any]
) -> dict[str, int]:
    """Count functions whose structure is unmeasured, including null measures."""
    unique = unique_functions(functions)
    return {
        "functions": len(unique),
        "unmeasured_functions": sum(
            function_is_unmeasured(function, file_record)
            or file_record.get("structure_confidence") == "low"
            for function in unique
        ),
        **{
            f"unmeasured_{field}": sum(
                function.get(field) is None for function in unique
            )
            for field in ("depth", "fan_out", "tree_size")
        },
    }


def unique_functions(functions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one record from each explicitly paired overload, in stable input order."""
    seen: set[str] = set()
    result = []
    for function in functions:
        identifier = function.get("id", "")
        pair = function.get("overload_pair")
        key = min(identifier, pair) if pair else identifier
        if key in seen:
            continue
        seen.add(key)
        result.append(function)
    return result


def _measure_costs(function: dict[str, Any], params: CostParameters) -> dict[str, int]:
    """Nesting and vague-name costs; present only when their strength is on."""
    costs = {}
    if params.sn > 0:
        costs["nesting"] = _quadratic_excess(
            function.get("max_nesting") or 0, params.n0, 1, MICRO
        )
    if params.sm > 0:
        costs["vague_names"] = _quadratic_excess(
            function.get("vague_names") or 0, params.nm0, 1, MICRO
        )
    return costs


def _delegation_cost(
    functions: list[dict[str, Any]], params: CostParameters
) -> dict[str, int]:
    """Quadratic cost of one-call wrappers above the tolerated share (``dg0``).

    Counts only functions with an exact ``delegates`` flag, so other languages
    cost nothing. Present only when ``sd`` is on.
    """
    if params.sd <= 0:
        return {}
    flagged = [
        fn
        for fn in functions
        if fn.get("delegates") is not None and not fn.get("exempt_role")
    ]
    delegating = sum(1 for fn in flagged if fn["delegates"])
    excess = delegating * MICRO - params.dg0 * len(flagged)
    cost = _square_ratio(max(0, excess), MICRO, MICRO)
    return {"delegation": cost} if cost else {}


def _name_cost(issues: Any, params: CostParameters) -> int:
    raw = len(set(issues)) * params.name_unit
    return min(raw, params.name_cap)


def _quadratic_excess(value: int, comfort: int, scale: int, weight: int) -> int:
    return _square_ratio(max(0, value - comfort), scale, weight)


def _quadratic_shortfall(value: int, comfort: int, weight: int) -> int:
    return _square_ratio(max(0, comfort - value), comfort, weight)


def _square_ratio(numerator: int, denominator: int, weight: int) -> int:
    if denominator <= 0:
        raise ValueError("cost scale must be positive")
    return numerator * numerator * weight // (denominator * denominator)


def _linear(value: int, scale: int, weight: int) -> int:
    if scale <= 0:
        raise ValueError("cost scale must be positive")
    return max(0, value) * weight // scale


def _apply_caps(
    costs: dict[str, int], caps: tuple[tuple[str, int], ...]
) -> dict[str, int]:
    limits = dict(caps)
    return {name: min(value, limits.get(name, value)) for name, value in costs.items()}
