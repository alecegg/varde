"""Deterministic regularized logistic fits for personal preferences."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from varde_dev.calibrate.rating.fit import fit as fit_ratings

L2_STRENGTH = 1.0
ITERATIONS = 200
MIN_MATCHES_PER_COMPONENT = 5
FOLD_COUNT = 5
HELD_OUT_FOLD = 0
PRECISION = 8


def canonicalize_labels(
    labels: Sequence[Mapping[str, Any]],
    units: Sequence[Mapping[str, Any]],
    rater_id: str,
) -> list[tuple[str, str, str, str]]:
    """Convert order-shown A/B choices into canonical item-id matches."""
    unit_by_id = {str(unit["id"]): unit for unit in units}
    matches = []
    for label in labels:
        if label.get("rater_id") != rater_id:
            continue
        unit_id = str(label.get("unit_id", ""))
        unit = unit_by_id.get(unit_id)
        if unit is None or unit.get("kind", "pair") != "pair":
            continue
        item_ids = unit.get("item_ids")
        order = label.get("order_shown")
        choice = label.get("choice")
        if (
            not isinstance(item_ids, list)
            or len(item_ids) != 2
            or not isinstance(order, list)
            or len(order) != 2
            or set(order) != set(item_ids)
        ):
            raise ValueError(f"invalid order_shown for pair label {unit_id}")
        left, right = sorted(map(str, item_ids))
        if choice == "tie":
            outcome = "tie"
        elif choice in {"A", "B"}:
            winner = str(order[0 if choice == "A" else 1])
            outcome = "x" if winner == left else "y"
        else:
            continue
        matches.append((str(unit["pair_group_id"]), left, right, outcome))
    return sorted(matches)


def fit_profile(
    matches: Sequence[tuple[str, str, str, str]],
    item_components: Mapping[str, Mapping[str, float]],
    item_groups: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Fit standardized component weights and report deterministic diagnostics."""
    canonical = _canonical_matches(matches, item_components)
    component_names = tuple(
        sorted({name for values in item_components.values() for name in values})
    )
    means, scales, standardized, constants = _standardize(
        item_components, component_names
    )
    active = tuple(name for name in component_names if name not in constants)
    vectors = {
        item_id: tuple(standardized[item_id][name] for name in active)
        for item_id in sorted(item_components)
    }
    training, held_out = _split_matches(canonical)
    coefficients = _solve(training, vectors, active)
    errors = _standard_errors(training, vectors, active, coefficients)
    weights = {
        name: {
            "weight": round(coefficients.get(name, 0.0), PRECISION),
            "standard_error": round(errors.get(name, 0.0), PRECISION),
            "interval_95": [
                round(
                    coefficients.get(name, 0.0) - 1.96 * errors.get(name, 0.0),
                    PRECISION,
                ),
                round(
                    coefficients.get(name, 0.0) + 1.96 * errors.get(name, 0.0),
                    PRECISION,
                ),
            ],
            "mean": round(means[name], PRECISION),
            "scale": round(scales[name], PRECISION),
        }
        for name in component_names
    }
    group_items = _group_items(canonical)
    if item_groups is not None:
        group_items = {
            group: sorted(item for item, owner in item_groups.items() if owner == group)
            for group in sorted(set(item_groups.values()) | set(group_items))
        }
        for group, x, y, _ in canonical:
            if item_groups.get(x) != group or item_groups.get(y) != group:
                raise ValueError(f"match items do not belong to group {group!r}")
    rating_matches = [(group, x, y, outcome) for group, x, y, outcome in canonical]
    ratings = fit_ratings(
        rating_matches,
        [
            (group, item_id)
            for group, item_ids in group_items.items()
            for item_id in item_ids
        ],
    )
    under_determined_components = [
        name
        for name in active
        if len(training) < MIN_MATCHES_PER_COMPONENT * len(active)
    ]
    return {
        "components": list(component_names),
        "weights": weights,
        "constant_components": list(constants),
        "under_determined": bool(under_determined_components),
        "under_determined_components": under_determined_components,
        "held_out_pair_accuracy": _held_out_accuracy(held_out, vectors, coefficients),
        "dislikes_most": {
            "by_group": _dislikes_by_group(
                ratings, group_items, item_components, standardized, coefficients
            ),
            "predicted_worst_pairs": _worst_pairs(canonical, vectors, coefficients),
        },
    }


def _canonical_matches(
    matches: Sequence[tuple[str, str, str, str]],
    item_components: Mapping[str, Mapping[str, float]],
) -> list[tuple[str, str, str, str]]:
    result = []
    for group, iter_first, iter_second, iter_outcome in matches:
        if iter_outcome not in {"x", "y", "tie"}:
            raise ValueError(f"invalid match outcome: {iter_outcome!r}")
        if iter_first not in item_components or iter_second not in item_components:
            raise ValueError(
                f"match references item without components: {iter_first}, {iter_second}"
            )
        first, second, outcome = iter_first, iter_second, iter_outcome
        if iter_first == iter_second:
            raise ValueError("match items must be different")
        if iter_first > iter_second:
            first, second = iter_second, iter_first
            outcome = {"x": "y", "y": "x", "tie": "tie"}[iter_outcome]
        result.append((group, first, second, outcome))
    return sorted(result)


def _standardize(
    items: Mapping[str, Mapping[str, float]], names: Sequence[str]
) -> tuple[
    dict[str, float], dict[str, float], dict[str, dict[str, float]], tuple[str, ...]
]:
    means = {}
    scales = {}
    constants = []
    for name in names:
        values = [float(items[item].get(name, 0.0)) for item in sorted(items)]
        if any(not math.isfinite(value) for value in values):
            raise ValueError(f"component {name!r} must contain finite numbers")
        mean = math.fsum(values) / len(values)
        variance = math.fsum((value - mean) ** 2 for value in values) / len(values)
        scale = math.sqrt(variance)
        means[name] = mean
        scales[name] = scale
        if scale == 0.0:
            constants.append(name)
    standardized = {
        item_id: {
            name: 0.0
            if scales[name] == 0.0
            else (float(values.get(name, 0.0)) - means[name]) / scales[name]
            for name in names
        }
        for item_id, values in items.items()
    }
    return means, scales, standardized, tuple(constants)


def _split_matches(
    matches: Sequence[tuple[str, str, str, str]],
) -> tuple[list[tuple[str, str, str, str]], list[tuple[str, str, str, str]]]:
    training, held_out = [], []
    for match in matches:
        key = "\0".join(match[:3]).encode("utf-8")
        fold = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % FOLD_COUNT
        (held_out if fold == HELD_OUT_FOLD else training).append(match)
    if not training and held_out:
        return list(held_out), []
    return training, held_out


def _solve(
    matches: Sequence[tuple[str, str, str, str]],
    vectors: Mapping[str, tuple[float, ...]],
    names: Sequence[str],
) -> dict[str, float]:
    size = len(names)
    coefficients = [0.0] * size
    if size == 0:
        return {}
    for _ in range(ITERATIONS):
        gradient = [-L2_STRENGTH * value for value in coefficients]
        information = [
            [L2_STRENGTH if row == col else 0.0 for col in range(size)]
            for row in range(size)
        ]
        for _, x, y, outcome in matches:
            difference = [a - b for a, b in zip(vectors[x], vectors[y], strict=True)]
            probability = _sigmoid(
                math.fsum(a * b for a, b in zip(coefficients, difference, strict=True))
            )
            observed = 0.5 if outcome == "tie" else float(outcome == "x")
            for row in range(size):
                gradient[row] += (observed - probability) * difference[row]
                for col in range(size):
                    information[row][col] += (
                        probability
                        * (1.0 - probability)
                        * difference[row]
                        * difference[col]
                    )
        step = _linear_solve(information, gradient)
        coefficients = [
            value + delta for value, delta in zip(coefficients, step, strict=True)
        ]
    return dict(zip(names, coefficients, strict=True))


def _standard_errors(
    matches: Sequence[tuple[str, str, str, str]],
    vectors: Mapping[str, tuple[float, ...]],
    names: Sequence[str],
    coefficients: Mapping[str, float],
) -> dict[str, float]:
    size = len(names)
    if size == 0:
        return {}
    information = [
        [L2_STRENGTH if row == col else 0.0 for col in range(size)]
        for row in range(size)
    ]
    values = [coefficients[name] for name in names]
    for _, x, y, _ in matches:
        difference = [a - b for a, b in zip(vectors[x], vectors[y], strict=True)]
        probability = _sigmoid(
            math.fsum(a * b for a, b in zip(values, difference, strict=True))
        )
        curvature = probability * (1.0 - probability)
        for row in range(size):
            for col in range(size):
                information[row][col] += curvature * difference[row] * difference[col]
    return {
        name: math.sqrt(
            max(
                0.0,
                _linear_solve(information, [float(row == col) for row in range(size)])[
                    col
                ],
            )
        )
        for col, name in enumerate(names)
    }


def _held_out_accuracy(
    matches: Sequence[tuple[str, str, str, str]],
    vectors: Mapping[str, tuple[float, ...]],
    coefficients: Mapping[str, float],
) -> float | None:
    if not matches:
        return None
    names = tuple(coefficients)
    values = [coefficients[name] for name in names]
    scores = []
    for _, x, y, outcome in matches:
        delta = math.fsum(
            weight * (a - b)
            for weight, a, b in zip(values, vectors[x], vectors[y], strict=True)
        )
        if outcome == "tie":
            scores.append(0.5)
        else:
            scores.append(float((delta >= 0.0) == (outcome == "x")))
    return round(math.fsum(scores) / len(scores), PRECISION)


def _dislikes_by_group(
    ratings: Mapping[str, Mapping[str, Any]],
    groups: Mapping[str, Sequence[str]],
    components: Mapping[str, Mapping[str, float]],
    standardized: Mapping[str, Mapping[str, float]],
    coefficients: Mapping[str, float],
) -> dict[str, list[dict[str, Any]]]:
    result = {}
    for group, item_ids in sorted(groups.items()):
        ordered = sorted(
            item_ids, key=lambda item: (float(ratings[item]["rating"]), item)
        )
        best = ordered[-1]
        result[group] = []
        for item_id in ordered[:10]:
            contributions = [
                (
                    name,
                    round(
                        coefficients[name]
                        * (standardized[item_id][name] - standardized[best][name]),
                        PRECISION,
                    ),
                )
                for name in sorted(coefficients)
            ]
            drivers = [
                {"component": name, "contribution": contribution}
                for name, contribution in sorted(
                    contributions, key=lambda pair: (pair[1], pair[0])
                )
                if contribution < 0
            ][:3]
            result[group].append(
                {
                    "item_id": item_id,
                    "rating": ratings[item_id]["rating"],
                    "components": dict(sorted(components[item_id].items())),
                    "driving_components": drivers,
                }
            )
    return result


def _worst_pairs(
    matches: Sequence[tuple[str, str, str, str]],
    vectors: Mapping[str, tuple[float, ...]],
    coefficients: Mapping[str, float],
) -> list[dict[str, Any]]:
    names = tuple(coefficients)
    values = [coefficients[name] for name in names]
    scored = []
    for group, x, y, outcome in matches:
        delta = math.fsum(
            weight * (a - b)
            for weight, a, b in zip(values, vectors[x], vectors[y], strict=True)
        )
        probability = _sigmoid(delta)
        likelihood = (
            2 * probability * (1 - probability)
            if outcome == "tie"
            else (probability if outcome == "x" else 1 - probability)
        )
        predicted = (
            "tie" if abs(probability - 0.5) < 0.05 else x if probability > 0.5 else y
        )
        scored.append(
            {
                "group_id": group,
                "item_ids": [x, y],
                "chosen": "tie" if outcome == "tie" else x if outcome == "x" else y,
                "predicted": predicted,
                "observed_probability": round(likelihood, PRECISION),
            }
        )
    return sorted(
        scored,
        key=lambda row: (row["observed_probability"], row["group_id"], row["item_ids"]),
    )[:10]


def _group_items(
    matches: Sequence[tuple[str, str, str, str]],
) -> dict[str, list[str]]:
    groups: dict[str, set[str]] = defaultdict(set)
    for group, x, y, _ in matches:
        groups[group].update((x, y))
    return {group: sorted(items) for group, items in sorted(groups.items())}


def _linear_solve(
    matrix: Sequence[Sequence[float]], vector: Sequence[float]
) -> list[float]:
    rows = [list(row) + [value] for row, value in zip(matrix, vector, strict=True)]
    size = len(rows)
    for pivot in range(size):
        divisor = rows[pivot][pivot]
        for column in range(pivot, size + 1):
            rows[pivot][column] /= divisor
        for row in range(size):
            if row == pivot:
                continue
            factor = rows[row][pivot]
            for column in range(pivot, size + 1):
                rows[row][column] -= factor * rows[pivot][column]
    return [rows[row][size] for row in range(size)]


def _sigmoid(value: float) -> float:
    if value >= 0:
        tail = math.exp(-value)
        return 1.0 / (1.0 + tail)
    head = math.exp(value)
    return head / (1.0 + head)


def canonical_labels_hash(labels: Sequence[Mapping[str, Any]]) -> str:
    records = sorted(
        json.dumps(label, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        for label in labels
    )
    payload = "\n".join(records).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
