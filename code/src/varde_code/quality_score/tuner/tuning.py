"""Pure strength fitting over precomputed component debt vectors."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from ..calibration import Calibration
from ..fixedpoint import MICRO

_ORDER = ("A", "wL", "w", "lam", "cFs", "ts", "kappa_F", "structure")
_PROFILE_ORDER = ("A", "wL", "w", "structure")
_COMPONENT_STRENGTH = {
    "small_side": "A",
    "long_side": "wL",
    "cognitive": "w",
    "fragmentation": "structure",
    "module_fragmentation": "structure",
    "depth": "structure",
    "fan_out": "structure",
    "tree_size": "structure",
    "names": "names",
}
_UNMEASURED = frozenset({"comments", "formatting", "uncapped_names"})


@dataclass(frozen=True)
class SampleVectors:
    """Vectors for one sample: target, original, judges, and optional attacks."""

    id: str
    versions: Mapping[str, Mapping[str, int]]
    gaming: Mapping[str, Mapping[str, int]] | None = None
    unmeasured_differences: Mapping[str, tuple[str, ...]] | None = None


@dataclass(frozen=True)
class ConstraintMargin:
    sample_id: str
    challenger: str
    margin: int
    passed: bool


@dataclass(frozen=True)
class CalibrationResult:
    strengths: dict[str, int]
    margins: tuple[ConstraintMargin, ...]
    held_out_id: str
    held_out_passed: bool
    leave_one_out: dict[str, bool]
    validated: bool
    reasons: tuple[str, ...]
    blocking_components: tuple[str, ...] = ()
    label: str = "not validated"
    profile: dict[str, object] | None = None


def tune(
    samples: list[SampleVectors],
    calibration: Calibration,
    *,
    held_out_id: str | None = None,
    gaming_margin: int = 0,
    tie_tolerance: int = 0,
) -> CalibrationResult:
    """Fit strengths on development samples and evaluate the stable held-out sample."""
    ordered = _ordered_samples(samples)
    if len(ordered) < 2:
        raise ValueError("tuning requires at least two samples")
    held = held_out_id or _held_out_id(ordered)
    if held not in {sample.id for sample in ordered}:
        raise ValueError(f"unknown held-out sample: {held}")
    development = [sample for sample in ordered if sample.id != held]
    starting = dict(calibration.global_strengths)
    strengths = _coordinate_descent(
        development, starting, calibration, gaming_margin, tie_tolerance
    )
    margins = _margins(ordered, strengths, gaming_margin, tie_tolerance)
    held_margins = [item for item in margins if item.sample_id == held]
    held_passed = bool(held_margins) and all(item.passed for item in held_margins)
    gaming_passed = all(
        item.passed
        for item in margins
        if item.challenger.startswith("gaming:") and item.sample_id != held
    )
    has_development_gaming = any(sample.gaming for sample in development)
    reasons = []
    if not held_passed:
        reasons.append("held-out sample did not rank its target first")
    if not gaming_passed:
        reasons.append("development gaming constraints were not met")
    if not has_development_gaming:
        reasons.append("development gaming constraints were not supplied")
    validated = held_passed and gaming_passed and has_development_gaming
    label = "validated" if validated else "not validated"
    return CalibrationResult(
        strengths,
        tuple(margins),
        held,
        held_passed,
        _leave_one_out(ordered, starting, calibration, gaming_margin, tie_tolerance),
        validated,
        tuple(reasons),
        label=label,
        profile=_profile_record(calibration, strengths, label) if validated else None,
    )


def recalibrate(
    user_targets: Mapping[str, Mapping[str, int]],
    shipped_state: Calibration,
    *,
    samples: list[SampleVectors] | None = None,
    gaming_margin: int = 0,
) -> CalibrationResult:
    """Fit edited targets from shipped strengths; omit profile when infeasible."""
    base = {sample.id: sample for sample in (samples or [])}
    adjusted: list[SampleVectors] = []
    if not base:
        components = tuple(
            sorted({name for target in user_targets.values() for name in target})
        )
        return CalibrationResult(
            dict(shipped_state.global_strengths),
            (),
            "",
            False,
            {},
            False,
            ("shipped sample comparison vectors are required",),
            components,
            "not validated",
            None,
        )
    unknown_targets = set(user_targets) - set(base)
    if unknown_targets:
        raise ValueError(
            f"unknown user target sample ids: {', '.join(sorted(unknown_targets))}"
        )
    for sample_id, sample in sorted(base.items()):
        target = user_targets.get(sample_id)
        if target is None:
            adjusted.append(sample)
            continue
        required = set(sample.versions["smoothed"])
        if set(target) != required:
            raise ValueError(
                f"user target {sample_id} components must be exactly: "
                f"{', '.join(sorted(required))}"
            )
        versions = dict(sample.versions)
        versions["smoothed"] = dict(target)
        adjusted.append(
            SampleVectors(
                sample.id, versions, sample.gaming, sample.unmeasured_differences
            )
        )
    result = _fit_user(adjusted, shipped_state, gaming_margin)
    if any(not item.passed for item in result.margins):
        return result
    gaming_unchecked = not any(sample.gaming for sample in adjusted)
    label = "user-edited, gaming-unchecked" if gaming_unchecked else "user-edited"
    profile = _profile_record(shipped_state, result.strengths, label)
    return CalibrationResult(
        result.strengths,
        result.margins,
        result.held_out_id,
        result.held_out_passed,
        result.leave_one_out,
        result.validated,
        result.reasons,
        result.blocking_components,
        label,
        profile,
    )


def _fit_user(
    samples: list[SampleVectors], calibration: Calibration, margin: int
) -> CalibrationResult:
    starting = dict(calibration.global_strengths)
    ordered = _ordered_samples(samples)
    held = _held_out_id(ordered) if len(ordered) > 1 else ""
    development = (
        [sample for sample in ordered if sample.id != held] if held else ordered
    )
    strengths = _coordinate_descent(
        development, starting, calibration, margin, 0, coordinates=_PROFILE_ORDER
    )
    constraints = _margins(ordered, strengths, margin, 0)
    failed = [entry for entry in constraints if not entry.passed]
    held_constraints = [entry for entry in constraints if entry.sample_id == held]
    held_passed = bool(held_constraints) and all(
        entry.passed for entry in held_constraints
    )
    blocking = tuple(
        sorted(
            {
                component
                for entry in failed
                for component in _active_components(samples, entry)
            }
        )
    )
    reasons = []
    if failed:
        reasons.append("user target is infeasible within configured strength limits")
    if not held:
        reasons.append("user recalibration has no held-out sample")
    elif not held_passed:
        reasons.append("held-out user sample did not rank its target first")
    validated = not failed and bool(held) and held_passed
    return CalibrationResult(
        strengths,
        tuple(constraints),
        held,
        held_passed,
        {},
        not failed,
        tuple(reasons),
        blocking,
        "validated" if validated else "not validated",
    )


def _ordered_samples(samples: list[SampleVectors]) -> list[SampleVectors]:
    result = sorted(samples, key=lambda sample: sample.id)
    if len({sample.id for sample in result}) != len(result):
        raise ValueError("sample ids must be unique")
    for sample in result:
        if "smoothed" not in sample.versions or "original" not in sample.versions:
            raise ValueError(
                f"sample {sample.id} requires smoothed and original vectors"
            )
        keys = set(sample.versions["smoothed"])
        if any(set(vector) != keys for vector in sample.versions.values()):
            raise ValueError(
                f"sample {sample.id} vectors must use identical components"
            )
    return result


def _held_out_id(samples: list[SampleVectors]) -> str:
    ids = "\n".join(sample.id for sample in samples).encode("utf-8")
    digest = hashlib.blake2b(ids, digest_size=16).digest()
    return samples[int.from_bytes(digest, "big") % len(samples)].id


def _coordinate_descent(
    samples: list[SampleVectors],
    starting: dict[str, int],
    calibration: Calibration,
    gaming_margin: int,
    tolerance: int,
    *,
    coordinates: tuple[str, ...] = _ORDER,
) -> dict[str, int]:
    strengths = dict(starting)
    for _ in range(3):
        changed = False
        for name in coordinates:
            if name not in strengths:
                continue
            options = _grid(name, starting[name], calibration)
            current_loss = _objective(
                samples, strengths, starting, gaming_margin, tolerance
            )
            candidates = []
            for candidate in options:
                trial = dict(strengths)
                trial[name] = candidate
                if name == "ts":
                    trial["dps"] = candidate // 4
                    trial["ks"] = candidate * 3 // 4
                candidates.append(
                    (
                        _objective(samples, trial, starting, gaming_margin, tolerance),
                        abs(candidate - starting[name]),
                        candidate,
                    )
                )
            best_loss, _, best_value = min(candidates)
            if best_loss < current_loss:
                strengths[name] = best_value
                changed = True
        if not changed:
            break
    return strengths


def _grid(name: str, start: int, calibration: Calibration) -> tuple[int, ...]:
    if name == "A":
        candidates = (MICRO, 2 * MICRO, 4 * MICRO)
    elif name == "wL":
        candidates = (300_000, 600_000, MICRO)
    elif name == "lam":
        candidates = (150_000, 300_000, 600_000)
    else:
        candidates = (start // 2, start, start * 2)
    limit_name = _profile_name(name)
    bounds = calibration.limits.get("strength", {}).get(limit_name)
    if bounds is None:
        bounds = (500_000, 2_000_000)
    anchor = calibration.global_strengths.get(name, start)
    low, high = anchor * bounds[0] // MICRO, anchor * bounds[1] // MICRO
    return tuple(sorted({min(high, max(low, value)) for value in candidates}))


def _objective(
    samples: list[SampleVectors],
    strengths: dict[str, int],
    starting: dict[str, int],
    margin: int,
    tolerance: int,
) -> int:
    loss = sum(
        max(0, -item.margin) for item in _margins(samples, strengths, margin, tolerance)
    )
    deviation = sum(
        abs(strengths[name] - starting.get(name, strengths[name]))
        * MICRO
        // max(1, starting.get(name, strengths[name]))
        for name in strengths
    )
    return loss * 100_000_000 + deviation


def _margins(
    samples: list[SampleVectors],
    strengths: dict[str, int],
    gaming_margin: int,
    tie_tolerance: int,
) -> list[ConstraintMargin]:
    output = []
    for sample in samples:
        target = sample.versions["smoothed"]
        for name, vector in sorted(sample.versions.items()):
            if name == "smoothed":
                continue
            gap = _weighted(vector, strengths) - _weighted(target, strengths)
            tie_allowed = _only_unmeasured_diff(sample, name)
            passed = gap >= 0 or (tie_allowed and gap >= -tie_tolerance)
            output.append(
                ConstraintMargin(
                    sample.id,
                    name,
                    gap - (tie_tolerance if tie_allowed else 0),
                    passed,
                )
            )
        for name, vector in sorted((sample.gaming or {}).items()):
            gap = _weighted(vector, strengths) - _weighted(target, strengths)
            output.append(
                ConstraintMargin(
                    sample.id,
                    f"gaming:{name}",
                    gap - gaming_margin,
                    gap >= gaming_margin,
                )
            )
    return output


def _weighted(vector: Mapping[str, int], strengths: Mapping[str, int]) -> int:
    return sum(
        value * strengths.get(_COMPONENT_STRENGTH.get(name, name), MICRO) // MICRO
        for name, value in vector.items()
    )


def _only_unmeasured_diff(sample: SampleVectors, challenger: str) -> bool:
    diff = (sample.unmeasured_differences or {}).get(challenger, ())
    if not diff or not set(diff).issubset(_UNMEASURED):
        return False
    return all(
        sample.versions[challenger].get(name) == sample.versions["smoothed"].get(name)
        for name in set(sample.versions[challenger]) | set(sample.versions["smoothed"])
        if name not in _UNMEASURED
    )


def _leave_one_out(
    samples: list[SampleVectors],
    starting: dict[str, int],
    calibration: Calibration,
    margin: int,
    tolerance: int,
) -> dict[str, bool]:
    diagnostic = {}
    for omitted in samples:
        train = [sample for sample in samples if sample.id != omitted.id]
        if not train:
            diagnostic[omitted.id] = False
            continue
        fitted = _coordinate_descent(train, starting, calibration, margin, tolerance)
        check = _margins([omitted], fitted, margin, tolerance)
        diagnostic[omitted.id] = bool(check) and all(item.passed for item in check)
    return diagnostic


def _active_components(
    samples: list[SampleVectors], constraint: ConstraintMargin
) -> set[str]:
    sample = next(item for item in samples if item.id == constraint.sample_id)
    target = sample.versions["smoothed"]
    challenger_name = constraint.challenger.removeprefix("gaming:")
    challenger = (
        sample.gaming[challenger_name]
        if constraint.challenger.startswith("gaming:") and sample.gaming
        else sample.versions[challenger_name]
    )
    return {name for name in target if target[name] != challenger[name]}


def _profile_name(name: str) -> str:
    return {
        "A": "small_side",
        "wL": "long_side",
        "w": "cognitive",
        "structure": "structure",
        "kappa_F": "structure",
        "lam": "cognitive",
        "cFs": "structure",
        "ts": "structure",
    }.get(name, name)


def _profile_record(
    calibration: Calibration, strengths: Mapping[str, int], label: str
) -> dict[str, object]:
    strength: dict[str, str] = {}
    for profile_name, global_name in (
        ("small_side", "A"),
        ("long_side", "wL"),
        ("cognitive", "w"),
        ("structure", "structure"),
        ("names", "names"),
    ):
        initial = calibration.global_strengths.get(global_name, MICRO)
        current = strengths.get(global_name, initial)
        multiplier = current * MICRO // max(1, initial)
        strength[profile_name] = _decimal(multiplier)
    languages = {
        name: {"strength": dict(strength), "validation": {"state": label}}
        for name in sorted(calibration.languages)
    }
    return {
        "profile": {
            "id": "user-recalibration",
            "formula": calibration.formula,
            "base_calibration": calibration.id,
        },
        "languages": languages,
    }


def _decimal(value: int) -> str:
    whole, fraction = divmod(value, MICRO)
    return f"{whole}.{fraction:06d}".rstrip("0").rstrip(".")
