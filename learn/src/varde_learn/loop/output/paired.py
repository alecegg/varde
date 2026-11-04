"""Summarize repeated current/candidate eval runs."""

from __future__ import annotations

from typing import Any

MIN_COMPARISON_RUNS = 3


def record_status(record: dict[str, Any]) -> str:
    if record.get("blocked") or not record.get("total_assertions", 0):
        return "inconclusive"
    if record.get("outcome") != "completed" or record.get(
        "passed_assertions"
    ) != record.get("total_assertions"):
        return "fail"
    return "pass"


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    arms = {
        name: [record for record in records if record.get("config") == config]
        for name, config in (("current", "without_skill"), ("candidate", "with_skill"))
    }
    included = {
        name: sum(record_status(record) != "inconclusive" for record in runs)
        for name, runs in arms.items()
    }
    inconclusive = {name: len(runs) - included[name] for name, runs in arms.items()}
    cases = [
        {
            "eval_id": eval_id,
            **{
                name: _summarize_arm(
                    [record for record in runs if record.get("eval_id") == eval_id]
                )
                for name, runs in arms.items()
            },
        }
        for eval_id in sorted({record.get("eval_id", "") for record in records})
    ]
    statuses = [record_status(record) for record in records]
    overall = max(
        statuses,
        key=lambda status: {"pass": 0, "inconclusive": 1, "fail": 2}.get(status, 1),
        default="inconclusive",
    )
    return {
        "status": overall,
        "evidence": "comparison"
        if all(value >= MIN_COMPARISON_RUNS for value in included.values())
        else "screen",
        "variance": _variance(
            [float(status == "pass") for status in statuses if status != "inconclusive"]
        ),
        "minimum_runs_per_arm": MIN_COMPARISON_RUNS,
        "included_runs": included,
        "inconclusive_runs": inconclusive,
        "cost": {key: _total_cost(records, key) for key in ("evaluated", "judge")},
        "cost_by_arm": {name: _cost_arm(runs) for name, runs in arms.items()},
        "runs": [
            {
                "eval_id": record.get("eval_id"),
                "config": record.get("config"),
                "run": record.get("run"),
                "status": record_status(record),
                "cost": record.get("cost", {}),
                "assertions": record.get("assertions", []),
            }
            for record in records
        ],
        "cases": cases,
    }


def _summarize_arm(runs: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [record for record in runs if record_status(record) != "inconclusive"]
    rates = [float(record_status(record) == "pass") for record in eligible]
    assertion_rates = [
        record["pass_rate"]
        for record in runs
        if record_status(record) != "inconclusive"
        and isinstance(record.get("pass_rate"), (int, float))
    ]
    return {
        "runs": len(runs),
        "included_runs": len(eligible),
        "inconclusive_runs": len(runs) - len(eligible),
        "pass_rate": _mean(rates),
        "variance": _variance(rates),
        "assertion_pass_rate": _mean(assertion_rates),
    }


def _cost_arm(runs: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    tokens: dict[str, Any] = {}
    measured, measured_tokens = {}, {}
    for key in ("evaluated", "judge"):
        cost_values, token_values = [], []
        for record in runs:
            cost = record.get("cost", {})
            if isinstance(cost.get(key), (int, float)):
                cost_values.append(cost[key])
            token = (
                cost.get("tokens", {}).get(key)
                if isinstance(cost.get("tokens"), dict)
                else None
            )
            if isinstance(token, int):
                token_values.append(token)
        result[key] = round(sum(cost_values), 4) if cost_values else "unavailable"
        tokens[key] = sum(token_values) if token_values else "unavailable"
        measured[key], measured_tokens[key] = len(cost_values), len(token_values)
    return {
        **result,
        "tokens": tokens,
        "measured_runs": measured,
        "measured_token_runs": measured_tokens,
    }


def _total_cost(records: list[dict[str, Any]], key: str) -> float | str:
    values = [record.get("cost", {}).get(key) for record in records]
    values = [value for value in values if isinstance(value, (int, float))]
    return round(sum(values), 4) if values else "unavailable"


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _variance(values: list[float]) -> float | None:
    average = _mean(values)
    return (
        round(sum((value - average) ** 2 for value in values) / len(values), 4)
        if average is not None
        else None
    )
