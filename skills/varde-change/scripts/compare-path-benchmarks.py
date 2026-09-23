#!/usr/bin/env python3
"""Compare per-path Varde Change benchmark artifacts."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare baseline and optimized path benchmark iterations."
    )
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return value


def load_catalog(path: Path) -> list[dict[str, Any]]:
    catalog = load_json(path)
    if catalog.get("schema_version") != 1:
        raise SystemExit("catalog schema_version must equal 1")
    routes = catalog.get("routes")
    if not isinstance(routes, list) or not routes:
        raise SystemExit("catalog routes must be a non-empty array")
    seen: set[str] = set()
    for route in routes:
        if not isinstance(route, dict):
            raise SystemExit("catalog routes must be objects")
        route_id = route.get("id")
        if not isinstance(route_id, str) or not route_id:
            raise SystemExit("every route needs a non-empty id")
        if route_id in seen:
            raise SystemExit(f"duplicate route id: {route_id}")
        seen.add(route_id)
        if not isinstance(route.get("eval_id"), int):
            raise SystemExit(f"route {route_id} needs an integer eval_id")
    return routes


def numeric_usage(usage: Any) -> dict[str, float] | None:
    fields = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    if not isinstance(usage, dict) or not any(
        isinstance(usage.get(field), (int, float)) for field in fields
    ):
        return None
    return {
        field: float(usage.get(field, 0))
        if isinstance(usage.get(field, 0), (int, float))
        else 0.0
        for field in fields
    }


def load_optional_json(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.strip():
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def read_runs(iteration: Path, eval_id: int) -> list[dict[str, Any]]:
    eval_dir = iteration / f"eval-{eval_id}" / "with_skill"
    if not eval_dir.is_dir():
        raise SystemExit(f"benchmark evaluation directory not found: {eval_dir}")
    run_dirs = sorted(
        path for path in eval_dir.glob("run-*") if path.is_dir()
    )
    if not run_dirs:
        raise SystemExit(f"no benchmark runs found: {eval_dir}")

    runs: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        timing = load_json(run_dir / "timing.json")
        grading = load_json(run_dir / "grading.json")
        raw = load_optional_json(run_dir / "raw.json")
        usage = numeric_usage(timing.get("usage"))
        tokens = sum(usage.values()) if usage is not None else None
        models = raw.get("modelUsage", {})
        canonical_models = []
        if isinstance(models, dict):
            canonical_models = sorted(
                {
                    model.get("canonicalModel")
                    for model in models.values()
                    if isinstance(model, dict)
                    and isinstance(model.get("canonicalModel"), str)
                }
            )
        runs.append(
            {
                "passed": int(grading.get("passed", 0)),
                "total": int(grading.get("total", 0)),
                "tokens": tokens,
                "cache_read_input_tokens": (
                    usage["cache_read_input_tokens"]
                    if usage is not None
                    else None
                ),
                "duration_seconds": float(timing.get("duration_ms", 0)) / 1000,
                "workflow_cycles": int(raw.get("num_turns", 0)),
                "run_outcome": grading.get("run_outcome", "completed"),
                "judge_outcome": grading.get("judge_outcome", "not_needed"),
                "canonical_models": canonical_models,
            }
        )
    return runs


def rounded(value: float) -> float:
    return round(value, 1)


def ratio(value: float) -> float:
    return round(value, 4)


def mean(values: list[float]) -> float:
    return rounded(statistics.fmean(values))


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(run["passed"] for run in runs)
    total = sum(run["total"] for run in runs)
    measured = [run for run in runs if run["tokens"] is not None]
    tokens = sum(run["tokens"] for run in measured)
    measured_passed = sum(run["passed"] for run in measured)
    efficiency = (measured_passed / tokens * 1000) if tokens else None
    return {
        "runs": len(runs),
        "assertions": {"passed": passed, "total": total},
        "pass_rate": ratio(passed / total) if total else None,
        "tokens": {
            "mean": mean([run["tokens"] for run in measured])
            if measured
            else None,
            "total": int(tokens) if measured else None,
            "measured_runs": len(measured),
            "unavailable_runs": len(runs) - len(measured),
        },
        "cache_read_input_tokens": {
            "mean": mean(
                [run["cache_read_input_tokens"] for run in measured]
            )
            if measured
            else None
        },
        "time_seconds": {
            "mean": mean([run["duration_seconds"] for run in runs])
            if runs
            else None
        },
        "workflow_cycles": {
            "mean": mean([run["workflow_cycles"] for run in runs])
            if runs
            else None
        },
        "token_efficiency": {
            "successful_assertions_per_1000_tokens": (
                ratio(efficiency) if efficiency is not None else None
            )
        },
        "outcomes": {
            "completed": sum(
                run["run_outcome"] == "completed" for run in runs
            ),
            "timed_out": sum(
                run["run_outcome"] == "timed_out" for run in runs
            ),
            "judge_timed_out": sum(
                run["judge_outcome"] == "timed_out" for run in runs
            ),
        },
        "canonical_models": sorted(
            {
                model
                for run in runs
                for model in run["canonical_models"]
            }
        ),
    }


def percent_delta(baseline: float | None, current: float | None) -> float | None:
    if baseline in (None, 0) or current is None:
        return None
    return rounded((current - baseline) / baseline * 100)


def compare(
    baseline: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    usage_cohort_match = (
        baseline["runs"] == current["runs"]
        and baseline["tokens"]["measured_runs"]
        == current["tokens"]["measured_runs"]
    )
    return {
        "pass_rate": (
            ratio(current["pass_rate"] - baseline["pass_rate"])
            if baseline["pass_rate"] is not None
            and current["pass_rate"] is not None
            else None
        ),
        "tokens_percent": (
            percent_delta(
                baseline["tokens"]["mean"], current["tokens"]["mean"]
            )
            if usage_cohort_match
            else None
        ),
        "cache_read_input_tokens_percent": (
            percent_delta(
                baseline["cache_read_input_tokens"]["mean"],
                current["cache_read_input_tokens"]["mean"],
            )
            if usage_cohort_match
            else None
        ),
        "time_seconds_percent": percent_delta(
            baseline["time_seconds"]["mean"],
            current["time_seconds"]["mean"],
        ),
        "workflow_cycles_percent": percent_delta(
            baseline["workflow_cycles"]["mean"],
            current["workflow_cycles"]["mean"],
        ),
        "token_efficiency_percent": (
            percent_delta(
                baseline["token_efficiency"][
                    "successful_assertions_per_1000_tokens"
                ],
                current["token_efficiency"][
                    "successful_assertions_per_1000_tokens"
                ],
            )
            if usage_cohort_match
            else None
        ),
        "usage_cohort_match": usage_cohort_match,
        "canonical_models_match": (
            baseline["canonical_models"] == current["canonical_models"]
        ),
    }


def main() -> None:
    args = parse_args()
    if not args.baseline.is_dir():
        raise SystemExit(f"baseline iteration not found: {args.baseline}")
    if not args.current.is_dir():
        raise SystemExit(f"current iteration not found: {args.current}")

    routes = load_catalog(args.catalog)
    route_results: dict[str, Any] = {}
    baseline_runs: list[dict[str, Any]] = []
    current_runs: list[dict[str, Any]] = []
    paired_baseline_runs: list[dict[str, Any]] = []
    paired_current_runs: list[dict[str, Any]] = []
    for route in routes:
        route_baseline_runs = read_runs(args.baseline, route["eval_id"])
        route_current_runs = read_runs(args.current, route["eval_id"])
        baseline_runs.extend(route_baseline_runs)
        current_runs.extend(route_current_runs)
        for baseline_run, current_run in zip(
            route_baseline_runs, route_current_runs
        ):
            if (
                baseline_run["tokens"] is not None
                and current_run["tokens"] is not None
            ):
                paired_baseline_runs.append(baseline_run)
                paired_current_runs.append(current_run)
        baseline = summarize(route_baseline_runs)
        current = summarize(route_current_runs)
        route_results[route["id"]] = {
            "eval_id": route["eval_id"],
            "baseline": baseline,
            "current": current,
            "delta": compare(baseline, current),
        }

    baseline_portfolio = summarize(baseline_runs)
    current_portfolio = summarize(current_runs)
    paired_baseline = summarize(paired_baseline_runs)
    paired_current = summarize(paired_current_runs)
    result = {
        "schema_version": 1,
        "routes": route_results,
        "portfolio": {
            "baseline": baseline_portfolio,
            "current": current_portfolio,
            "delta": compare(baseline_portfolio, current_portfolio),
            "paired_measured": {
                "baseline": paired_baseline,
                "current": paired_current,
                "delta": compare(paired_baseline, paired_current),
            },
        },
    }
    output = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(output, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
