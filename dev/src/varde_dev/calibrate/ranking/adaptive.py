"""Adaptive judge loop with an injected round runner."""

from collections.abc import Callable, Mapping, Sequence
from typing import TypedDict

from varde_dev.calibrate.ranking.core import rank_labels
from varde_dev.calibrate.ranking.plan import plan_next


class AdaptiveSettings(TypedDict, total=False):
    k: int
    repeats: int
    rule: Mapping[str, object]
    max_calls: int
    lens_count: int


def run_adaptive_loop(
    labels: Sequence[Mapping[str, object]],
    units: Sequence[Mapping[str, object]],
    items: Sequence[Mapping[str, object]],
    rater_id: str,
    run_round: Callable[[list[tuple[str, str, str]]], Sequence[Mapping[str, object]]],
    *,
    settings: AdaptiveSettings | None = None,
) -> dict[str, object]:
    """Ask an injected runner for rounds until ranking stops or calls run out.

    A future panel `rate --adaptive` command can supply the guarded panel runner.
    This function performs no client invocation itself.
    """
    options = settings or {}
    k = options.get("k", 1)
    repeats = options.get("repeats", 2)
    lens_count = options.get("lens_count", 1)
    rule = options.get("rule")
    max_calls = options.get("max_calls", 100)
    collected = list(labels)
    calls = 0
    budget_exhausted = False
    while True:
        result = rank_labels(collected, units, items, rater_id, rule=rule)
        if result["stop_state"]["stop"]:
            break
        plan = plan_next(
            collected,
            units,
            items,
            rater_id,
            settings={"k": k, "repeats": repeats, "lens_count": lens_count},
        )
        pairs = plan["pairs"]
        if not pairs:
            break
        round_calls = len(pairs) * 2 * repeats * lens_count
        if calls + round_calls > max_calls:
            budget_exhausted = True
            break
        round_labels = list(run_round(pairs))
        if not round_labels:
            break
        collected.extend(round_labels)
        calls += round_calls
    final = rank_labels(collected, units, items, rater_id, rule=rule)
    final["calls_used"] = calls
    final["budget_exhausted"] = not final["stop_state"]["stop"] and (
        budget_exhausted or calls >= max_calls
    )
    return final
