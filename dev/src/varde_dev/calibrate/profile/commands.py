"""Command-line handler for fitting a personal preference profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shlex
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Never

from varde_dev.calibrate.profile.fit import (
    FOLD_COUNT,
    HELD_OUT_FOLD,
    ITERATIONS,
    L2_STRENGTH,
    MIN_MATCHES_PER_COMPONENT,
    canonical_labels_hash,
    canonicalize_labels,
    fit_profile,
)
from varde_dev.calibrate.reports.dataset import read_dataset_files


def _raise_scorer_error(error: Exception) -> Never:
    raise error


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m varde_dev.calibrate profile")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--rater", required=True)
    parser.add_argument("--components", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument(
        "--scorer",
        default=os.environ.get(
            "VARDE_CALIBRATE_SCORER",
            "varde code score --facts {facts} --calibration {calibration} --debug",
        ),
        help=(
            "scorer command template (default: VARDE_CALIBRATE_SCORER or "
            "varde code score ... --debug, which prints raw scorer JSON)"
        ),
    )
    args = parser.parse_args(argv)
    try:
        _run_profile(
            args.dataset, args.rater, args.components, args.scorer, args.calibration
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"calibrate profile: {error}", file=sys.stderr)
        return 1
    return 0


def _run_profile(
    dataset_path: Path,
    rater_id: str,
    components_path: Path | None,
    scorer: str = "varde code score",
    calibration_path: Path | None = None,
) -> Path:
    dataset = read_dataset_files(dataset_path)
    item_components = (
        _read_components(components_path)
        if components_path is not None
        else _score_items(dataset_path, dataset["items"], scorer, calibration_path)
    )
    item_by_id = {str(item["id"]): item for item in dataset["items"]}
    unknown_items = sorted(set(item_components) - set(item_by_id))
    if unknown_items:
        raise ValueError(f"components reference unknown item: {unknown_items[0]}")
    missing_items = sorted(set(item_by_id) - set(item_components))
    if missing_items:
        raise ValueError(f"components are missing item: {missing_items[0]}")
    if not item_components:
        raise ValueError("components file has no items")
    rater_labels = [
        label for label in dataset["labels"] if label.get("rater_id") == rater_id
    ]
    matches = canonicalize_labels(rater_labels, dataset["units"], rater_id)
    memberships = {
        str(item["id"]): str(item.get("pair_group_id", ""))
        for item in dataset["items"]
        if str(item["id"]) in item_components
    }
    result = fit_profile(matches, item_components, memberships)
    profile = {
        "schema_version": 1,
        "rater_id": rater_id,
        **result,
        "input_hashes": {
            "labels_sha256": canonical_labels_hash(rater_labels),
            "components_sha256": _components_hash(components_path, item_components),
        },
        "fit_settings": {
            "algorithm": "standardized pairwise logistic regression (Newton/IRLS)",
            "l2_strength": L2_STRENGTH,
            "iterations": ITERATIONS,
            "fold_count": FOLD_COUNT,
            "held_out_fold": HELD_OUT_FOLD,
            "minimum_matches_per_component": MIN_MATCHES_PER_COMPONENT,
        },
    }
    destination = dataset_path / "profile.json"
    destination.write_text(
        json.dumps(profile, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(destination)
    return destination


def _components_hash(
    path: Path | None, item_components: Mapping[str, Mapping[str, float]]
) -> str:
    if path is not None:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    payload = json.dumps(item_components, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _score_items(
    dataset_path: Path,
    items: Sequence[Mapping[str, object]],
    scorer: str,
    calibration_path: Path | None,
) -> dict[str, dict[str, float]]:
    if calibration_path is None:
        raise ValueError("--calibration is required when scorer mode is used")
    result = {}
    for item in items:
        item_id = str(item["id"])
        facts_value = item.get("facts_path")
        if not isinstance(facts_value, str) or not facts_value:
            raise ValueError(f"item {item_id} requires a facts_path")
        facts_path = Path(facts_value)
        if not facts_path.is_absolute():
            facts_path = dataset_path / facts_path
        substitutions = {
            "item_id": item_id,
            "item_path": str(item.get("path", "")),
            "facts": str(facts_path),
            "calibration": str(calibration_path),
        }
        try:
            command = [part.format_map(substitutions) for part in shlex.split(scorer)]
        except KeyError as error:
            raise ValueError(
                f"unknown --scorer placeholder: {error.args[0]}"
            ) from error
        if not command:
            raise ValueError("--scorer must contain a command")
        completed = subprocess.run(  # noqa: S603 - Runs the configured local calibration command with explicit arguments.
            command,
            capture_output=True,
            check=False,
            text=True,
        )
        if completed.returncode:
            raise ValueError(
                f"scorer failed for item {item_id}: {completed.stderr.strip()}"
            )
        try:
            payload = json.loads(completed.stdout)
            breakdown = payload["breakdown"]
            values: dict[str, float] = {}
            for component in breakdown:
                name = component["name"]
                debt = component["debt"]
                if (
                    not isinstance(name, str)
                    or isinstance(debt, bool)
                    or not isinstance(debt, (int, float))
                ):
                    _raise_scorer_error(TypeError("invalid component breakdown"))
                values[name] = float(debt)
            if not values:
                _raise_scorer_error(ValueError("empty component breakdown"))
            result[item_id] = values
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError(
                f"invalid scorer output for item {item_id}: {error}"
            ) from error
    return result


def _read_components(path: Path) -> dict[str, dict[str, float]]:
    items: dict[str, dict[str, float]] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, Mapping):
            raise TypeError(f"components line {line_number} must be an object")
        item_id = record.get("item_id")
        values = record.get("components")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError(f"components line {line_number} requires item_id")
        if item_id in items:
            raise ValueError(f"duplicate component item_id: {item_id}")
        if not isinstance(values, Mapping) or not values:
            raise ValueError(f"components for {item_id} must be a non-empty object")
        normalized = {}
        for name, value in values.items():
            if not isinstance(name, str) or not name:
                raise ValueError(
                    f"component names for {item_id} must be non-empty strings"
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"component {name!r} for {item_id} must be numeric")
            if not math.isfinite(value):
                raise ValueError(f"component {name!r} for {item_id} must be finite")
            normalized[name] = float(value)
        items[item_id] = normalized
    return items
