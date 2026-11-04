"""Deterministic adaptive pair selection and stopping rules."""

from __future__ import annotations

import math
from itertools import pairwise
from statistics import NormalDist

from varde_dev.calibrate.rating.fit import win_probability


def _canonical_pair(group: str, x: str, y: str) -> tuple[str, str, str]:
    return (group, x, y) if x < y else (group, y, x)


def _played_pairs(played: list[tuple[str, ...]]) -> set[tuple[str, str, str]]:
    return {_canonical_pair(match[0], match[1], match[2]) for match in played}


def _has_rank_path(
    items: tuple[str, ...],
    played: list[tuple[str, ...]],
    group: str,
    ordered: list[str],
) -> bool:
    wins: dict[str, set[str]] = {item: set() for item in items}
    for match in played:
        if len(match) != 4 or match[0] != group:
            continue
        _, x, y, outcome = match
        if outcome == "x":
            wins[x].add(y)
        elif outcome == "y":
            wins[y].add(x)
    for intermediate in items:
        for item in items:
            if intermediate in wins[item]:
                wins[item].update(wins[intermediate])
    if any(item in wins[item] for item in items):
        return False
    return all(following in wins[previous] for previous, following in pairwise(ordered))


def _memberships(groups: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
    return {group: tuple(sorted(set(items))) for group, items in sorted(groups.items())}


def _bootstrap_pairs(group: str, items: tuple[str, ...]) -> list[tuple[str, str, str]]:
    if len(items) < 2:
        return []
    pairs = [
        _canonical_pair(group, items[index], items[index + 1])
        for index in range(0, len(items) - 1, 2)
    ]
    if len(items) % 2:
        pairs.append(_canonical_pair(group, items[-1], items[0]))
    return pairs


def _pair_score(ratings: dict[str, object], x: str, y: str) -> float:
    left, right = ratings[x], ratings[y]
    left_error = left["standard_error"]
    right_error = right["standard_error"]
    if not isinstance(left_error, (float, int)) or not isinstance(
        right_error, (float, int)
    ):
        return math.inf
    difference_error = math.hypot(float(left_error), float(right_error))
    closeness = 1.0 - abs(2.0 * win_probability(ratings, x, y) - 1.0)
    return difference_error * closeness


def next_pairs(
    ratings: dict[str, object],
    played: list[tuple[str, ...]],
    groups: dict[str, list[str]],
    k: int = 1,
) -> list[tuple[str, str, str]]:
    """Return up to k canonical (group, item, item) match requests."""
    if k < 1:
        return []
    members = _memberships(groups)
    played_set = _played_pairs(played)
    if not played_set:
        return [
            pair
            for group, items in members.items()
            for pair in _bootstrap_pairs(group, items)
        ]
        # The first call is a complete balanced round, independent of k.

    unplayed_candidates = []
    repeated_candidates = []
    for group, items in members.items():
        possible = [
            _canonical_pair(group, x, y)
            for index, x in enumerate(items)
            for y in items[index + 1 :]
        ]
        unplayed = [pair for pair in possible if pair not in played_set]
        for pair in unplayed:
            _, x, y = pair
            unplayed_candidates.append((_pair_score(ratings, x, y), pair))
        for pair in possible:
            if pair in played_set:
                _, x, y = pair
                repeated_candidates.append((_pair_score(ratings, x, y), pair))
    candidates = unplayed_candidates or repeated_candidates
    candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    selected = []
    selected_set = set()
    for _, pair in candidates:
        if pair in selected_set:
            continue
        selected.append(pair)
        selected_set.add(pair)
        if len(selected) == k:
            break
    return selected


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    rows = [row[:] + [value] for row, value in zip(matrix, vector, strict=True)]
    for pivot in range(len(rows)):
        divisor = rows[pivot][pivot]
        for column in range(pivot, len(rows) + 1):
            rows[pivot][column] /= divisor
        for row in range(len(rows)):
            if row == pivot:
                continue
            factor = rows[row][pivot]
            for column in range(pivot, len(rows) + 1):
                rows[row][column] -= factor * rows[pivot][column]
    return [row[-1] for row in rows]


def _difference_standard_error(
    ratings: dict[str, object],
    items: tuple[str, ...],
    played: list[tuple[str, ...]],
    group: str,
    x: str,
    y: str,
) -> float:
    positions = {item: index for index, item in enumerate(items)}
    information = [
        [float(row == column) for column in range(len(items))]
        for row in range(len(items))
    ]
    for match in played:
        match_group, left, right = match[:3]
        if match_group != group:
            continue
        probability = win_probability(ratings, left, right)
        curvature = probability * (1.0 - probability)
        left_index, right_index = positions[left], positions[right]
        information[left_index][left_index] += curvature
        information[right_index][right_index] += curvature
        information[left_index][right_index] -= curvature
        information[right_index][left_index] -= curvature
    contrast = [0.0] * len(items)
    contrast[positions[x]], contrast[positions[y]] = 1.0, -1.0
    solved = _solve(information, contrast)
    variance = sum(
        value * weight for value, weight in zip(solved, contrast, strict=True)
    )
    return math.sqrt(max(variance, 0.0))


def _confidence(rule: dict[str, object]) -> float:
    confidence = float(rule.get("confidence", 0.9))
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return confidence


def _z_value(rule: dict[str, object]) -> float:
    confidence = _confidence(rule)
    return NormalDist().inv_cdf((1.0 + confidence) / 2.0)


def _group_budget(size: int) -> int:
    return max(1, math.ceil(size * math.log2(size))) if size > 1 else 0


def stop_state(
    ratings: dict[str, object],
    played: list[tuple[str, ...]],
    groups: dict[str, list[str]],
    rule: dict[str, object],
) -> dict[str, object]:
    """Report whether all adjacent rating intervals separate or budget is spent."""
    confidence_level = _confidence(rule)
    z_value = _z_value(rule)
    members = _memberships(groups)
    summaries: dict[str, dict[str, tuple[float | str, float | str]]] = {}
    group_status: dict[str, str] = {}
    for group, items in members.items():
        ordered = sorted(
            items, key=lambda item: (-float(ratings[item]["rating"]), item)
        )
        intervals: dict[str, tuple[float | str, float | str]] = {}
        numeric_intervals = []
        for item in ordered:
            estimate = ratings[item]
            error = estimate["standard_error"]
            rating = float(estimate["rating"])
            if not isinstance(error, (float, int)):
                interval = ("undetermined", "undetermined")
            else:
                margin = z_value * float(error)
                interval = (round(rating - margin, 8), round(rating + margin, 8))
                numeric_intervals.append((item, interval))
            intervals[item] = interval
        summaries[group] = intervals
        group_confident = len(items) <= 1 and len(numeric_intervals) == 0
        if len(items) <= 1 and numeric_intervals:
            group_confident = True
        if len(numeric_intervals) == len(items) and len(items) > 1:
            # A consistent outcome path certifies order for a noise-free oracle,
            # even when the ridge prior keeps posterior intervals broad.
            rank_path = _has_rank_path(items, played, group, ordered)
            posterior_confident = True
            for (previous_item, _), (following_item, _) in pairwise(numeric_intervals):
                gap = float(ratings[previous_item]["rating"]) - float(
                    ratings[following_item]["rating"]
                )
                difference_error = _difference_standard_error(
                    ratings, items, played, group, previous_item, following_item
                )
                if (
                    difference_error == 0.0
                    or NormalDist().cdf(gap / difference_error) < confidence_level
                ):
                    posterior_confident = False
            group_confident = rank_path or posterior_confident
        group_matches = sum(match[0] == group for match in played)
        configured_budget = rule.get("budget")
        budget = (
            int(configured_budget)
            if configured_budget is not None
            else _group_budget(len(items))
        )
        group_status[group] = (
            "confident"
            if group_confident
            else "budget"
            if group_matches >= budget
            else "open"
        )
    stopped = all(status != "open" for status in group_status.values())
    reason = (
        "confident"
        if stopped and all(status == "confident" for status in group_status.values())
        else "budget"
        if stopped
        else None
    )
    return {
        "stop": stopped,
        "reason": reason,
        "groups": summaries,
        "groups_status": group_status,
    }
