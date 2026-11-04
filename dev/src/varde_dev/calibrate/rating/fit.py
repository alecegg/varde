"""Deterministic Bradley-Terry maximum-likelihood ratings.

Ratings have an independent Gaussian N(0, 1) ridge prior. Outputs are rounded
to 8 decimal places.
"""

from __future__ import annotations

import math

PRIOR_PRECISION = 1.0
ITERATIONS = 200
PRECISION = 8
TOLERANCE = 1e-12


def _probability(delta: float) -> float:
    if delta >= 0:
        tail = math.exp(-delta)
        return 1.0 / (1.0 + tail)
    head = math.exp(delta)
    return head / (1.0 + head)


def win_probability(ratings: dict[str, object], x: str, y: str) -> float:
    """Return the Bradley-Terry probability that x beats y."""

    def value(item: str) -> float:
        rating = ratings[item]
        return float(rating["rating"]) if isinstance(rating, dict) else float(rating)

    return round(_probability(value(x) - value(y)), PRECISION)


def _linear_solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Solve a positive definite system by deterministic Gaussian elimination."""
    rows = [row[:] + [value] for row, value in zip(matrix, vector, strict=True)]
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


def _information(
    items: tuple[str, ...],
    scores: dict[str, float],
    matches: list[tuple[str, str, str]],
) -> list[list[float]]:
    index = {item: position for position, item in enumerate(items)}
    matrix = [[0.0 for _ in items] for _ in items]
    for position in range(len(items)):
        matrix[position][position] = PRIOR_PRECISION
    for x, y, _ in matches:
        ix, iy = index[x], index[y]
        p = _probability(scores[x] - scores[y])
        curvature = p * (1.0 - p)
        matrix[ix][ix] += curvature
        matrix[iy][iy] += curvature
        matrix[ix][iy] -= curvature
        matrix[iy][ix] -= curvature
    return matrix


def _solve(
    items: tuple[str, ...], matches: list[tuple[str, str, str]]
) -> dict[str, float]:
    scores = dict.fromkeys(items, 0.0)
    for _ in range(ITERATIONS):
        gradient = dict.fromkeys(items, 0.0)
        for x, y, outcome in matches:
            p = _probability(scores[x] - scores[y])
            observed = 0.5 if outcome == "tie" else float(outcome == "x")
            residual = observed - p
            gradient[x] += residual
            gradient[y] -= residual
        gradient = {
            item: value - scores[item] * PRIOR_PRECISION
            for item, value in gradient.items()
        }
        information = _information(items, scores, matches)
        step_values = _linear_solve(information, [gradient[item] for item in items])
        step = dict(zip(items, step_values, strict=True))
        for item in items:
            scores[item] += step[item]
        center = sum(scores.values()) / len(items)
        scores = {item: value - center for item, value in scores.items()}
        if max(abs(value) for value in step_values) < TOLERANCE:
            break
    return scores


def _standard_errors(
    items: tuple[str, ...],
    scores: dict[str, float],
    matches: list[tuple[str, str, str]],
) -> dict[str, float]:
    information = _information(items, scores, matches)
    inverse_diagonal = []
    for position in range(len(items)):
        basis = [0.0 for _ in items]
        basis[position] = 1.0
        inverse_column = _linear_solve(information, basis)
        inverse_diagonal.append(inverse_column[position])
    return {
        item: round(math.sqrt(inverse_diagonal[position]), PRECISION)
        for position, item in enumerate(items)
    }


def fit(
    matches: list[tuple[str, str, str, str]], items: list[tuple[str, str]]
) -> dict[str, dict[str, float | int | str]]:
    """Fit ratings for (group, item) pairs; matches are (group, x, y, outcome)."""
    memberships: dict[str, str] = {}
    for group, item in sorted(items):
        if item in memberships and memberships[item] != group:
            raise ValueError(f"item {item!r} belongs to multiple groups")
        memberships[item] = group
    canonical: list[tuple[str, str, str, str]] = []
    for group, iter_x, iter_y, iter_outcome in matches:
        if iter_outcome not in {"x", "y", "tie"}:
            raise ValueError(f"invalid match outcome: {iter_outcome!r}")
        x, y, outcome = iter_x, iter_y, iter_outcome
        gx, gy = memberships.get(iter_x), memberships.get(iter_y)
        if gx != gy or (gx is not None and gx != group) or gx is None:
            raise ValueError(
                f"match items {iter_x!r} and {iter_y!r} are in different groups"
            )
        if iter_x > iter_y:
            x, y = iter_y, iter_x
            outcome = {"x": "y", "y": "x", "tie": "tie"}[iter_outcome]
        canonical.append((group, x, y, outcome))
    canonical.sort()
    output: dict[str, dict[str, float | int | str]] = {}
    for group in sorted({group for group, _ in items}):
        members = tuple(
            sorted(item for item, owner in memberships.items() if owner == group)
        )
        group_matches = [
            (x, y, outcome) for g, x, y, outcome in canonical if g == group
        ]
        if len(members) == 1 or not group_matches:
            scores = dict.fromkeys(members, 0.0)
            errors = dict.fromkeys(members, "undetermined")
        else:
            scores = _solve(members, group_matches)
            errors = _standard_errors(members, scores, group_matches)
        for item in members:
            wins = ties = losses = 0
            for x, y, outcome in group_matches:
                if item not in (x, y):
                    continue
                result = (
                    outcome
                    if item == x
                    else ("y" if outcome == "x" else "x")
                    if outcome != "tie"
                    else "tie"
                )
                wins += result == "x"
                losses += result == "y"
                ties += result == "tie"
            output[item] = {
                "group_id": group,
                "rating": round(scores[item], PRECISION),
                "standard_error": errors[item],
                "matches_played": wins + ties + losses,
                "wins": wins,
                "ties": ties,
                "losses": losses,
            }
    return output
