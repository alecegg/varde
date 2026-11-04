"""Deterministic function, file, and scope quality scores."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from ..calibration import Calibration, EffectiveCalibration, Profile
from ..costs import (
    CostParameters,
    dominance_scale,
    file_costs,
    function_costs,
    function_is_unmeasured,
    module_fragmentation_cost,
    unique_functions,
)
from ..fixedpoint import MICRO, combine, score_for_tokens
from ..fixedpoint import ScopeScore as FixedScore
from ..smap import score_density

STRUCTURE = {"depth", "fan_out", "tree_size", "fragmentation", "module_fragmentation"}
FUNCTION_COMPONENTS = (
    "cognitive",
    "long_side",
    "small_side",
    "params",
    "names",
    "depth",
    "fan_out",
    "tree_size",
)


@dataclass(frozen=True)
class FunctionScore:
    id: str
    path: str
    line: int | None
    value: dict[str, int | None]
    comfort: dict[str, int | None]
    costs: dict[str, int]
    debt: int
    exempt_role: str | None


@dataclass(frozen=True)
class FileScore:
    path: str
    language: str
    tokens: int
    debt: int
    density: int
    score: int
    gate_score: int
    components: dict[str, int]
    function_values: dict[str, dict[str, int | None]]
    functions: tuple[FunctionScore, ...]
    worst_functions: tuple[FunctionScore, ...]
    exempt_from_floor: bool
    floor_exemption_reason: str | None
    excluded: str | None
    not_applicable: bool
    low_structure_confidence: bool = False
    points_lost: int = 0
    component_points_lost: dict[str, int] | None = None


@dataclass(frozen=True)
class ScopeScore:
    score: FixedScore | None
    tokens: int
    debt: int
    files: tuple[FileScore, ...]
    languages: dict[str, FixedScore]
    placeholder: bool = True


def score_scope(
    facts_records: list[dict[str, Any]],
    calibration: Calibration,
    profile: Profile | None = None,
    *,
    component_caps: dict[str, int] | None = None,
) -> ScopeScore:
    """Score records, retaining raw values and component costs for explanation."""
    records = sorted(facts_records, key=lambda row: row.get("path", ""))
    effective = {
        r["language"]: _effective(r["language"], calibration, profile)
        for r in records
        if r.get("language") in calibration.languages
    }
    module_costs = _module_cost_allocations(records, effective, component_caps)
    scored = tuple(
        _score_file(
            row,
            effective.get(row.get("language")),
            calibration,
            module_costs,
            component_caps,
        )
        for row in records
    )
    included = [
        f for f in scored if not f.excluded and not f.not_applicable and f.tokens > 0
    ]
    if not included:
        return ScopeScore(None, 0, 0, scored, {})
    token_total = sum(f.tokens for f in included)
    scope_fixed = combine([score_for_tokens(f.gate_score, f.tokens) for f in included])
    lost_numerator = sum(f.tokens * (100 * MICRO - f.gate_score) for f in included)
    lost = lost_numerator // token_total
    adjusted = _attribute_points(scored, lost)
    language_scores = {}
    for language in sorted({f.language for f in included}):
        child = [f for f in included if f.language == language]
        language_scores[language] = combine(
            [score_for_tokens(f.gate_score, f.tokens) for f in child]
        )
    return ScopeScore(
        scope_fixed,
        token_total,
        sum(f.debt for f in included),
        adjusted,
        language_scores,
    )


def _module_cost_allocations(
    records: list[dict[str, Any]],
    effective: dict[str, EffectiveCalibration],
    component_caps: dict[str, int] | None,
) -> dict[tuple[str, str], int]:
    allocations = {}
    for language, language_calibration in effective.items():
        groups: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            if record.get("language") != language:
                continue
            module = str(record.get("module") or record["path"].rsplit("/", 1)[0])
            groups.setdefault(module, []).append(record)
        params = _cost_parameters(language_calibration, component_caps)
        for rows in groups.values():
            counts = _module_fragment_counts(rows, params.t_frag)
            total = sum(counts.values())
            if not total:
                continue
            cost = module_fragmentation_cost(rows, params)
            for path, count in counts.items():
                allocations[(path, "module_fragmentation")] = cost * count // total
    return allocations


def _module_fragment_counts(
    rows: list[dict[str, Any]], threshold: int
) -> dict[str, int]:
    counts = {}
    for row in rows:
        if row.get("structure_confidence") == "low":
            continue
        counts[row["path"]] = sum(
            1
            for fn in unique_functions(row.get("functions", []))
            if fn.get("fragment_scope") == "module"
            and (fn.get("tokens") or 0) <= threshold
            and not fn.get("exempt_role")
            and not function_is_unmeasured(fn, row)
        )
    return counts


def rescore_without(scope_score: ScopeScore, component: str) -> ScopeScore:
    """Rescore retained files with one named component's cost removed."""
    rescored = []
    for file in scope_score.files:
        components = dict(file.components)
        components[component] = 0
        debt = sum(components.values())
        structure_cost = sum(components.get(name, 0) for name in STRUCTURE)
        gate_debt = debt - structure_cost if file.low_structure_confidence else debt
        rescored.append(
            replace(
                file,
                debt=debt,
                density=debt_density(debt, file.tokens),
                score=score_density(debt_density(debt, file.tokens)),
                gate_score=score_density(debt_density(gate_debt, file.tokens)),
                components=components,
                points_lost=0,
                component_points_lost=None,
            )
        )
    valid = [
        f for f in rescored if not f.excluded and not f.not_applicable and f.tokens > 0
    ]
    if not valid:
        return ScopeScore(None, 0, 0, tuple(rescored), {})
    total = sum(f.tokens for f in valid)
    scope_lost = sum(f.tokens * (100 * MICRO - f.gate_score) for f in valid) // total
    rescored = _attribute_points(rescored, scope_lost)
    language_scores = {
        language: combine(
            [
                score_for_tokens(f.gate_score, f.tokens)
                for f in valid
                if f.language == language
            ]
        )
        for language in sorted({f.language for f in valid})
    }
    return ScopeScore(
        combine([score_for_tokens(f.gate_score, f.tokens) for f in valid]),
        total,
        sum(f.debt for f in valid),
        tuple(rescored),
        language_scores,
    )


def explain(scope_score: ScopeScore) -> dict[str, Any]:
    """Return plain-data scores with placeholder status and exact roll-up."""
    return {
        "calibration": "placeholder; not validated",
        "score": _rational(scope_score.score)
        if scope_score.score is not None
        else None,
        "tokens": scope_score.tokens,
        "debt": scope_score.debt,
        "files": [_plain_data(f) for f in scope_score.files],
        "languages": {k: _rational(v) for k, v in scope_score.languages.items()},
    }


def _score_file(
    row: dict[str, Any],
    effective: EffectiveCalibration | None,
    calibration: Calibration,
    module_costs: dict[tuple[str, str], int],
    component_caps: dict[str, int] | None,
) -> FileScore:
    path, language = row.get("path", ""), row.get("language", "")
    excluded = row.get("excluded")
    if excluded or effective is None:
        return FileScore(
            path,
            language,
            0,
            0,
            0,
            0,
            0,
            {},
            {},
            (),
            (),
            False,
            None,
            excluded,
            effective is None,
        )
    params = _cost_parameters(effective, component_caps)
    strengths = effective.global_strengths
    functions = []
    diagnostic_record = {**row, "structure_confidence": "normal"}
    fn_components: dict[str, int] = {}
    file_tokens = row.get("tokens") or 0
    for fn in unique_functions(row.get("functions", [])):
        costs = function_costs(fn, params, file_record=diagnostic_record)
        scale = dominance_scale(
            fn.get("tokens") or 0, file_tokens, strengths.get("dominance", 0)
        )
        for name, value in costs.items():
            weighted = value * strengths.get(_strength(name), MICRO) // MICRO
            weighted = weighted * scale // MICRO
            capped = min(weighted, (component_caps or {}).get(name, weighted))
            fn_components[name] = fn_components.get(name, 0) + capped
        functions.append(
            FunctionScore(
                fn.get("id", ""),
                path,
                fn.get("line"),
                {name: fn.get(name) for name in FUNCTION_COMPONENTS}
                | _measure_values(fn, params),
                _comforts(params) | _measure_comforts(params),
                costs,
                sum(costs.values()),
                fn.get("exempt_role"),
            )
        )
    components = dict(fn_components)
    for name, value in file_costs(diagnostic_record, params).items():
        weighted = value * strengths.get(_strength(name), MICRO) // MICRO
        components[name] = components.get(name, 0) + min(
            weighted, (component_caps or {}).get(name, weighted)
        )
    module_cost = module_costs.get((path, "module_fragmentation"), 0)
    weighted_module_cost = module_cost * strengths.get("structure", MICRO) // MICRO
    components["module_fragmentation"] = min(
        weighted_module_cost,
        (component_caps or {}).get("module_fragmentation", weighted_module_cost),
    )
    debt = sum(components.values())
    tokens = max(0, row.get("tokens") or 0)
    density = debt * 1000 // max(1, tokens)
    score = score_density(density)
    structure_cost = sum(components.get(name, 0) for name in STRUCTURE)
    gate_debt = (
        debt - structure_cost if row.get("structure_confidence") == "low" else debt
    )
    gate_score = score_density(debt_density(gate_debt, tokens))
    y = effective.language.parameters["Y"]
    overhead = components.get("file_overhead", 0) + sum(
        params.A for fn in functions if not fn.exempt_role
    )
    exempt = overhead * 1000 >= _density_for_score(y) * tokens
    reasons = "fixed overhead reaches floor threshold" if exempt else None
    funcs = tuple(sorted(functions, key=lambda fn: (-fn.debt, fn.id)))
    return FileScore(
        path,
        language,
        tokens,
        debt,
        density,
        score,
        gate_score,
        components,
        {fn.id: fn.value for fn in functions},
        tuple(functions),
        funcs[:5],
        exempt,
        reasons,
        None,
        False,
        row.get("structure_confidence") == "low",
    )


def _effective(
    language: str, calibration: Calibration, profile: Profile | None
) -> EffectiveCalibration:
    if profile:
        return profile.for_language(language)
    lc = calibration.languages[language]
    return EffectiveCalibration(lc, dict(calibration.global_strengths))


def _cost_parameters(
    effective: EffectiveCalibration, component_caps: dict[str, int] | None = None
) -> CostParameters:
    allowed = CostParameters.__dataclass_fields__
    values = {
        key: value
        for key, value in effective.language.parameters.items()
        if key in allowed
    }
    values.update(
        {
            key: value
            for key, value in effective.global_strengths.items()
            if key in allowed
        }
    )
    for name in (
        "Plo",
        "Phi",
        "c0",
        "cs",
        "ss",
        "dps",
        "ks",
        "ts",
        "p0",
        "ps",
        "F0",
        "Fs",
        "o0",
        "os",
        "cmin",
        "t_frag",
        "cF0",
        "cFs",
        "dp0",
        "k0",
        "t0",
        "H",
        "n0",
        "nm0",
    ):
        if name in values:
            values[name] //= MICRO
    parameters: dict[str, Any] = values
    if component_caps is not None:
        parameters["component_caps"] = tuple(sorted(component_caps.items()))
    return CostParameters(**parameters)


def _strength(name: str) -> str:
    return {
        "cognitive": "w",
        "long_side": "wL",
        "small_side": "A",
        "depth": "structure",
        "fan_out": "structure",
        "tree_size": "structure",
        "fragmentation": "structure",
        "module_fragmentation": "structure",
        "names": "names",
        "nesting": "sn",
        "vague_names": "sm",
        "delegation": "sd",
    }.get(name, name)


def _measure_values(
    fn: dict[str, Any], params: CostParameters
) -> dict[str, int | None]:
    """Nesting and vague-name values of a function, only for strengths that are on."""
    values: dict[str, int | None] = {}
    if params.sn > 0:
        values["nesting"] = fn.get("max_nesting")
    if params.sm > 0:
        values["vague_names"] = fn.get("vague_names")
    return values


def _measure_comforts(params: CostParameters) -> dict[str, int | None]:
    comforts: dict[str, int | None] = {}
    if params.sn > 0:
        comforts["nesting"] = params.n0
    if params.sm > 0:
        comforts["vague_names"] = params.nm0
    return comforts


def _comforts(params: CostParameters) -> dict[str, int | None]:
    return {
        "cognitive": params.c0,
        "long_side": params.Phi,
        "small_side": params.Plo,
        "params": params.p0,
        "depth": params.dp0,
        "fan_out": params.k0,
        "tree_size": params.t0,
    }


def _density_for_score(score: int) -> int:
    """Return the first density whose score is at or below the floor."""
    low, high = 0, 30 * MICRO
    while low < high:
        mid = (low + high) // 2
        if score_density(mid) > score:
            low = mid + 1
        else:
            high = mid
    return low


def debt_density(debt: int, tokens: int) -> int:
    return debt * 1000 // max(1, tokens)


def _attribute_points(
    files: tuple[FileScore, ...] | list[FileScore], total_lost: int
) -> tuple[FileScore, ...]:
    included = [
        f for f in files if not f.excluded and not f.not_applicable and f.tokens > 0
    ]
    file_weights = {f.path: f.tokens * (100 * MICRO - f.gate_score) for f in included}
    file_points = _largest_remainder(
        file_weights, sum(file_weights.values()), total_lost
    )
    result = []
    for file in files:
        points = file_points.get(file.path, 0)
        denom = sum(file.components.values())
        component_points = (
            _largest_remainder(
                file.components,
                denom,
                points,
            )
            if denom and points
            else dict.fromkeys(file.components, 0)
        )
        result.append(
            replace(file, points_lost=points, component_points_lost=component_points)
        )
    return tuple(result)


def _largest_remainder(
    weights: dict[str, int], denominator: int, total: int
) -> dict[str, int]:
    """Allocate an integer total proportionally; ties resolve by key."""
    if not weights or denominator <= 0:
        return dict.fromkeys(weights, 0)
    floors = {key: total * weight // denominator for key, weight in weights.items()}
    remaining = total - sum(floors.values())
    order = sorted(
        weights, key=lambda key: (-(total * weights[key] % denominator), key)
    )
    for key in order[:remaining]:
        floors[key] += 1
    return floors


def _rational(score: FixedScore) -> dict[str, int]:
    return {"numerator": score.numerator, "denominator": score.denominator}


def _plain_data(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_plain_data(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain_data(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return _plain_data(asdict(value))
    return value
