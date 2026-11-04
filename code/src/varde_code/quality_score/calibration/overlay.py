"""User baseline overlay: saved examples that move the acceptable-quality region.

The overlay is read here, never by ``loading.py``. It holds the user's saved
examples and the thresholds ``calibrate`` derived from them (existing cal-1
keys only). ``effective_calibration`` substitutes those thresholds into the
parent calibration in process, so the calibration file format is unchanged.

``calibrate`` repeats the pure derivation of
``code/bench/quality-corpus/tools/baseline_region.calibrate`` (``code`` cannot import
``bench``); a test keeps the two equal. Integer arithmetic only.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from ..fixedpoint.arithmetic import MICRO
from .loading import Calibration

SCHEMA = 1
SOURCE = "custom"
# raw measure (raw_measure.py row key) -> cal-1 language threshold key
FITTED = {
    "cognitive": "c0",
    "depth": "dp0",
    "fan_out": "k0",
    "tree_size": "t0",
    "params": "p0",
    "tokens": "Phi",
}
ANCHOR_PERCENTILE = 90
LOW_PERCENTILE, HIGH_PERCENTILE = 50, 99
WEIGHT_OFFSET = 2  # w = k / (k + WEIGHT_OFFSET)
_TOP_KEYS = {
    "schema",
    "source",
    "parent_id",
    "parent_sha256",
    "language",
    "created",
    "sample",
    "metrics",
    "inherited",
}
_SAMPLE_KEYS = {"problem", "code_sha256", "code_path"}


class OverlayError(ValueError):
    """The overlay file is malformed or does not match its parent calibration."""


@dataclass(frozen=True)
class Sample:
    problem: str
    code_sha256: str
    code_path: str  # relative to the overlay's samples directory


@dataclass(frozen=True)
class Overlay:
    parent_id: str
    parent_sha256: str
    language: str
    created: str
    samples: tuple[Sample, ...]
    metrics: Mapping[str, int]  # cal-1 key -> raw threshold
    inherited: tuple[str, ...]  # fitted keys left at the parent value

    @property
    def source(self) -> str:
        return SOURCE


# ---- pure derivation (same arithmetic as baseline_region.calibrate) ---------


def nearest_rank(values: Sequence[int], percentile: int) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (percentile * len(ordered) + 99) // 100
    return ordered[max(rank, 1) - 1]


def shifted(default: int, anchor: int, k: int) -> int:
    """default + k/(k+2) * (anchor - default), rounded half up."""
    denominator = k + WEIGHT_OFFSET
    return default + (2 * k * (anchor - default) + denominator) // (2 * denominator)


def fit_threshold(
    default: int, values: Sequence[int], k: int, bounds: tuple[int, int] | None
) -> int:
    anchor = nearest_rank(values, ANCHOR_PERCENTILE)
    if k <= 0 or anchor is None:
        return default
    threshold = shifted(default, anchor, k)
    if bounds is None:
        return threshold
    return min(max(threshold, bounds[0]), bounds[1])


def corpus_bounds(values: Sequence[int]) -> tuple[int, int] | None:
    low = nearest_rank(values, LOW_PERCENTILE)
    high = nearest_rank(values, HIGH_PERCENTILE)
    return None if low is None or high is None else (low, high)


def calibrate(
    default_region: Mapping[str, int],
    examples: Sequence[Sequence[Mapping[str, Any]]],
    corpus: Mapping[str, Sequence[int]],
) -> dict[str, int]:
    """Thresholds (same keys as ``default_region``) from k example samples."""
    rows = [row for sample in examples for row in sample]
    region = dict(sorted(default_region.items()))
    for measure, key in FITTED.items():
        if key not in region:
            continue
        values = [int(r[measure]) for r in rows if r.get(measure) is not None]
        region[key] = fit_threshold(
            region[key],
            values,
            len(examples),
            corpus_bounds(list(corpus.get(measure, ()))),
        )
    return region


def default_region(calibration: Calibration, language: str) -> dict[str, int]:
    """The language's fitted raw thresholds from the parent calibration."""
    parameters = calibration.languages[language].parameters
    return {
        key: parameters[key] // MICRO for key in FITTED.values() if key in parameters
    }


# ---- build, render, read ----------------------------------------------------


def build_overlay(
    parent: Calibration,
    language: str,
    samples: Sequence[Sample],
    thresholds: Mapping[str, int],
    created: str,
) -> Overlay:
    parent_region = default_region(parent, language)
    inherited = tuple(
        sorted(k for k, v in thresholds.items() if parent_region.get(k) == v)
    )
    return Overlay(
        parent.id,
        parent.source_sha256,
        language,
        created,
        tuple(samples),
        dict(sorted(thresholds.items())),
        inherited,
    )


def render_overlay(overlay: Overlay) -> str:
    lines = [
        f"schema = {SCHEMA}",
        f'source = "{SOURCE}"',
        f'parent_id = "{overlay.parent_id}"',
        f'parent_sha256 = "{overlay.parent_sha256}"',
        f'language = "{overlay.language}"',
        f'created = "{overlay.created}"',
        "inherited = [" + ", ".join(f'"{k}"' for k in overlay.inherited) + "]",
        "",
    ]
    for sample in overlay.samples:
        lines += [
            "[[sample]]",
            f'problem = "{sample.problem}"',
            f'code_sha256 = "{sample.code_sha256}"',
            f'code_path = "{sample.code_path}"',
            "",
        ]
    lines.append("[metrics]")
    lines += [f"{key} = {value}" for key, value in sorted(overlay.metrics.items())]
    return "\n".join(lines) + "\n"


def read_overlay(text: str, parent: Calibration) -> Overlay:
    """Parse strictly; unknown keys or a parent hash mismatch raise OverlayError."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise OverlayError(f"overlay is not valid TOML: {exc}") from exc
    unknown = set(data) - _TOP_KEYS
    if unknown:
        raise OverlayError(f"unknown overlay keys: {sorted(unknown)}")
    if data.get("schema") != SCHEMA or data.get("source") != SOURCE:
        raise OverlayError("overlay schema or source is not supported")
    if data.get("parent_sha256") != parent.source_sha256:
        raise OverlayError("overlay parent_sha256 does not match the calibration")
    if data.get("parent_id") != parent.id:
        raise OverlayError("overlay parent_id does not match the calibration")
    language = _text(data, "language")
    if language not in parent.languages:
        raise OverlayError(f"overlay language {language!r} is not calibrated")
    metrics = _metrics(data.get("metrics"))
    inherited = tuple(data.get("inherited", ()))
    if not set(inherited) <= set(FITTED.values()):
        raise OverlayError("overlay inherited names an unknown key")
    return Overlay(
        parent.id,
        parent.source_sha256,
        language,
        _text(data, "created"),
        tuple(_sample(entry) for entry in data.get("sample", ())),
        metrics,
        inherited,
    )


def _text(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise OverlayError(f"overlay {key} must be a non-empty string")
    return value


def _metrics(table: Any) -> dict[str, int]:
    if not isinstance(table, dict) or not table:
        raise OverlayError("overlay metrics must be a non-empty table")
    unknown = set(table) - set(FITTED.values())
    if unknown:
        raise OverlayError(f"unknown overlay metrics: {sorted(unknown)}")
    for key, value in table.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise OverlayError(f"overlay metric {key} must be a non-negative integer")
    return dict(table)


def _sample(entry: Any) -> Sample:
    if not isinstance(entry, dict) or set(entry) != _SAMPLE_KEYS:
        raise OverlayError(f"overlay sample must have exactly {sorted(_SAMPLE_KEYS)}")
    sample = Sample(**{key: _text(entry, key) for key in _SAMPLE_KEYS})
    name = sample.code_path
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise OverlayError("overlay sample code_path must be a bare file name")
    return sample


def effective_calibration(parent: Calibration, overlay: Overlay) -> Calibration:
    """The parent calibration with the overlay thresholds substituted."""
    entry = parent.languages[overlay.language]
    parameters = {**entry.parameters}
    parameters.update({k: v * MICRO for k, v in overlay.metrics.items()})
    languages = {
        **parent.languages,
        overlay.language: replace(entry, parameters=parameters),
    }
    return replace(parent, languages=languages)
