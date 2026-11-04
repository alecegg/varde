"""Strict, deterministic readers for calibration and profile TOML files."""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..fixedpoint.arithmetic import MICRO, from_decimal, to_decimal

DEFAULT_STATE = "report-only"
GATING_STATES = frozenset({"panel-validated", "baseline-validated"})
VALIDATION_STATES = GATING_STATES | {DEFAULT_STATE}
# Shadow-mode measure keys: global strength -> the per-language threshold it needs.
# Absent keys mean "off"; a strength above 0 needs its threshold in every language.
MEASURE_STRENGTH_THRESHOLDS = {"sn": "n0", "sm": "nm0", "sd": "dg0"}
MEASURE_KEYS = frozenset(MEASURE_STRENGTH_THRESHOLDS) | frozenset(
    MEASURE_STRENGTH_THRESHOLDS.values()
)


@dataclass(frozen=True)
class LanguageCalibration:
    parameters: dict[str, int]
    validation: dict[str, Any]

    @property
    def state(self) -> str:
        return self.validation.get("state", DEFAULT_STATE)

    @property
    def threshold_x(self) -> int:
        return self.parameters["X"]


@dataclass(frozen=True)
class Calibration:
    id: str
    formula: str
    validated: bool
    global_strengths: dict[str, int]
    languages: dict[str, LanguageCalibration]
    limits: dict[str, dict[str, tuple[int, int]]]
    provenance: dict[str, dict[str, Any]]
    source_sha256: str

    @property
    def gating_available(self) -> bool:
        return self.validated

    def language_gating_available(self, language: str) -> bool:
        """True only for a known language whose state is a gating state."""
        entry = self.languages.get(language)
        return entry is not None and entry.state in GATING_STATES

    @property
    def output_label(self) -> str:
        if "placeholder" in self.id:
            return "placeholder; " + (
                "validated" if self.validated else "not validated"
            )
        return "validated" if self.validated else "not validated"


@dataclass(frozen=True)
class EffectiveCalibration:
    language: LanguageCalibration
    global_strengths: dict[str, int]


@dataclass(frozen=True)
class Profile:
    id: str
    formula: str
    base_calibration: str
    languages: dict[str, EffectiveCalibration]
    hash: str
    effective_hash: str
    profile_sha256: str

    def for_language(self, language: str) -> EffectiveCalibration:
        return self.languages.get(language, self._base_languages[language])

    # Retained as immutable-by-convention data for languages omitted in profile.
    _base_languages: dict[str, EffectiveCalibration]


def shipped_calibration_path() -> Path:
    """Path of the calibration file shipped with the package (id ``cal-2``)."""
    return Path(__file__).parent / "cal-1.toml"


def load_calibration(path: str | Path) -> Calibration:
    raw_bytes = Path(path).read_bytes()
    data = tomllib.loads(raw_bytes.decode("utf-8"))
    meta = _table(data, "calibration")
    global_values = _table(data, "global")
    languages = {
        name: _language(values)
        for name, values in _table(data, "language").items()
        if isinstance(values, dict)
    }
    validation = {
        name: values["validation"]
        for name, values in _table(data, "language").items()
        if isinstance(values, dict) and "validation" in values
    }
    limits = _limits(_table(data, "limits"))
    calibration_id = _required_str(meta, "id")
    formula = _required_str(meta, "formula")
    validated = meta.get("validated", False)
    if not isinstance(validated, bool):
        raise TypeError("calibration.validated must be a boolean")
    global_strengths = {
        key: _fixed(value, f"global.{key}") for key, value in global_values.items()
    }
    _check_measure_keys(global_strengths, languages, limits.get("measures", {}))
    return Calibration(
        calibration_id,
        formula,
        validated,
        global_strengths,
        languages,
        limits,
        validation,
        hashlib.sha256(raw_bytes).hexdigest(),
    )


def load_profile(path: str | Path, calibration: Calibration) -> Profile:
    raw_bytes = Path(path).read_bytes()
    raw = tomllib.loads(raw_bytes.decode("utf-8"))
    meta = _table(raw, "profile")
    profile_id = _required_str(meta, "id")
    formula = _required_str(meta, "formula")
    base_calibration = _required_str(meta, "base_calibration")
    if formula != calibration.formula:
        raise ValueError(
            f"profile formula {formula!r} does not match calibration formula "
            f"{calibration.formula!r}"
        )
    if base_calibration != calibration.id:
        raise ValueError(
            f"profile base_calibration {base_calibration!r} does not match "
            f"{calibration.id!r}"
        )

    base = {
        name: EffectiveCalibration(language, dict(calibration.global_strengths))
        for name, language in calibration.languages.items()
    }
    effective = dict(base)
    for language, settings in _table(raw, "languages").items():
        if language not in calibration.languages:
            raise ValueError(f"profile language {language!r} is not in calibration")
        if not isinstance(settings, dict):
            raise TypeError(f"profile languages.{language} must be a table")
        strength = _table(settings, "strength")
        thresholds = _table(settings, "thresholds")
        if set(settings) - {"strength", "thresholds", "validation"}:
            raise ValueError(
                f"profile languages.{language} contains unsupported fields"
            )
        updated_global = dict(calibration.global_strengths)
        for name, multiplier in strength.items():
            limit = calibration.limits.get("strength", {}).get(name)
            if limit is None:
                raise ValueError(f"profile strength {name!r} has no configured limits")
            multiplier_micro = _fixed(
                multiplier, f"languages.{language}.strength.{name}"
            )
            _check_limit(multiplier_micro, limit, f"strength {name}")
            target = _strength_target(name)
            if target not in updated_global:
                raise ValueError(f"profile strength {name!r} has no base value")
            updated_global[target] = updated_global[target] * multiplier_micro // MICRO

        parameters = dict(calibration.languages[language].parameters)
        for name, value in thresholds.items():
            limit = calibration.limits.get("thresholds", {}).get(name)
            if limit is None or name not in {"X", "Y", "cap"}:
                raise ValueError(f"profile threshold {name!r} has no configured limits")
            fixed = _fixed(value, f"languages.{language}.thresholds.{name}")
            _check_limit(fixed, limit, f"threshold {name}")
            parameters[name] = fixed
        # Validation is provenance only; a profile cannot replace shipped validation.
        effective[language] = EffectiveCalibration(
            LanguageCalibration(parameters, calibration.languages[language].validation),
            updated_global,
        )
    normalized = _jsonable(
        {
            name: {
                "language": value.language.parameters,
                "global": value.global_strengths,
            }
            for name, value in sorted(effective.items())
        }
    )
    digest = hashlib.blake2b(normalized, digest_size=32).hexdigest()
    profile_sha = hashlib.sha256(raw_bytes).hexdigest()
    return Profile(
        profile_id,
        formula,
        base_calibration,
        effective,
        digest,
        digest,
        profile_sha,
        base,
    )


def _language(values: dict[str, Any]) -> LanguageCalibration:
    validation = values.get("validation", {})
    if not isinstance(validation, dict):
        raise TypeError("language validation provenance must be a table")
    state = validation.get("state", DEFAULT_STATE)
    if state not in VALIDATION_STATES:
        raise ValueError(
            f"unknown language validation state {state!r}; "
            f"must be one of {sorted(VALIDATION_STATES)}"
        )
    parameters = {
        key: _fixed(value, f"language.{key}")
        for key, value in values.items()
        if key != "validation"
    }
    if not {"X", "Y", "cap"}.issubset(parameters):
        raise ValueError("language table requires X, Y, and cap thresholds")
    return LanguageCalibration(parameters, validation)


def _check_measure_keys(
    global_strengths: dict[str, int],
    languages: dict[str, LanguageCalibration],
    bounds: dict[str, tuple[int, int]],
) -> None:
    """Bound every present measure key; a strength above 0 needs its threshold."""
    for key in MEASURE_KEYS & global_strengths.keys():
        _check_measure_bound(global_strengths[key], key, bounds, f"global.{key}")
    for name, language in languages.items():
        for key in MEASURE_KEYS & language.parameters.keys():
            where = f"language.{name}.{key}"
            _check_measure_bound(language.parameters[key], key, bounds, where)
    for strength, threshold in MEASURE_STRENGTH_THRESHOLDS.items():
        if global_strengths.get(strength, 0) <= 0:
            continue
        missing = [n for n, v in languages.items() if threshold not in v.parameters]
        if missing:
            raise ValueError(
                f"global.{strength} is on but {threshold} is missing for "
                f"{', '.join(sorted(missing))}"
            )


def _check_measure_bound(
    value: int, key: str, bounds: dict[str, tuple[int, int]], where: str
) -> None:
    limit = bounds.get(key)
    if limit is None:
        raise ValueError(f"{where} has no configured limits.measures.{key}")
    if not limit[0] <= value <= limit[1]:
        low, high = (to_decimal(bound) for bound in limit)
        raise ValueError(f"{where} outside limits [{low}, {high}]")


def _limits(values: dict[str, Any]) -> dict[str, dict[str, tuple[int, int]]]:
    result: dict[str, dict[str, tuple[int, int]]] = {}
    for group, entries in values.items():
        if not isinstance(entries, dict):
            raise TypeError(f"limits.{group} must be a table")
        result[group] = {}
        for name, bounds in entries.items():
            if not isinstance(bounds, list) or len(bounds) != 2:
                raise ValueError(
                    f"limits.{group}.{name} must contain two decimal bounds"
                )
            low, high = (_fixed(bound, f"limits.{group}.{name}") for bound in bounds)
            if low > high:
                raise ValueError(
                    f"limits.{group}.{name} lower bound exceeds upper bound"
                )
            result[group][name] = (low, high)
    return result


def _fixed(value: Any, location: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value * MICRO
    if not isinstance(value, str):
        raise TypeError(f"{location} must be a decimal string or integer")
    try:
        return from_decimal(value)
    except ValueError as exc:
        raise ValueError(f"{location}: {exc}") from exc


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be a TOML table")
    return value


def _required_str(data: dict[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing or invalid {name}")
    return value


def _check_limit(value: int, bounds: tuple[int, int], description: str) -> None:
    if not bounds[0] <= value <= bounds[1]:
        low, high = (to_decimal(bound) for bound in bounds)
        label, name = description.split(" ", 1)
        raise ValueError(f"profile {label} outside limits for {name} [{low}, {high}]")


def _strength_target(name: str) -> str:
    return {
        "cognitive": "w",
        "long_side": "wL",
        "small_side": "A",
        "structure": "structure",
        "names": "names",
    }.get(name, name)


def _jsonable(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
