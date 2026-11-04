#!/usr/bin/env python3
"""Interleaved paired A/B harness for fast index scenarios."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

SCENARIOS = ("cold", "no_change", "edit1")
DEFAULT_LOCK = Path("/Users/alec/source/.varde-measure.lock")
SEED = 1729


def load_measurement(repo: Path):
    source = repo / "code/scripts/code-index/measure_index.py"
    spec = importlib.util.spec_from_file_location("measure_index", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load measurement scenarios from {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def interleaved_schedule(runs: int) -> list[tuple[str, int]]:
    schedule = []
    for run in range(runs):
        pair = ("a", "b") if run % 2 == 0 else ("b", "a")
        schedule.extend((side, run) for side in pair)
    return schedule


def paired_bootstrap(differences: list[float], *, samples: int = 2000) -> list[float]:
    if not differences:
        raise ValueError("at least one paired difference is required")
    rng = random.Random(SEED)  # noqa: S311 - Deterministic bootstrap sampling is not cryptographic.
    means = sorted(
        statistics.mean(rng.choices(differences, k=len(differences)))
        for _ in range(samples)
    )
    return [means[int(samples * 0.025)], means[min(int(samples * 0.975), samples - 1)]]


def output_path(path: Path, repo_a: Path, repo_b: Path) -> Path:
    resolved = path.resolve()
    for repo in (repo_a.resolve(), repo_b.resolve()):
        if (
            repo == resolved or repo in resolved.parents
        ) and "results" in resolved.relative_to(repo).parts:
            raise ValueError("--out cannot be under any repo results/ directory")
    return resolved


def lock_path(env: dict[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    return Path(values.get("VARDE_LOCK_DIR", str(DEFAULT_LOCK)))


def make_medium_fixture(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    fixture = directory / "repos" / "tiny"
    generator = Path(__file__).with_name("make_medium_fixture.py")
    result = subprocess.run(  # noqa: S603 - Runs the measured indexing command with constructed arguments.
        [sys.executable, str(generator), str(fixture)],
        check=True,
        capture_output=True,
        text=True,
    )
    metadata = json.loads(result.stdout)
    if metadata["file_count"] != 300 or len(metadata["tree_hash"]) != 64:
        raise ValueError("medium fixture generator returned invalid metadata")
    return fixture


def measure_one(module, scenario: str, fixture_kind: str) -> list[dict]:
    if fixture_kind == "tiny":
        return module.execute(scenario, 1)
    with tempfile.TemporaryDirectory(prefix="varde-medium-") as temp:
        fixture = make_medium_fixture(Path(temp))
        module.FIXTURES = fixture.parents[1]
        return module.execute(scenario, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-a", required=True, type=Path)
    parser.add_argument("--repo-b", required=True, type=Path)
    parser.add_argument("--fixture", choices=("tiny", "medium"), default="tiny")
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.runs < 1 or (not args.dry_run and args.runs < 30):
        parser.error(
            "measurement requires --runs >=30 (dry-run accepts smaller counts)"
        )
    try:
        out = output_path(args.out, args.repo_a, args.repo_b)
    except ValueError as error:
        parser.error(str(error))
    lock = lock_path()
    if not lock.is_dir():
        raise SystemExit(f"measurement lock is not held: {lock}")
    schedule = interleaved_schedule(1 if args.dry_run else args.runs)
    print("schedule: " + " ".join(f"{side.upper()}{run + 1}" for side, run in schedule))
    if args.dry_run:
        print("dry-run: PASS (measurements not run)")
        return 0
    summaries = {}
    for scenario in SCENARIOS:
        paired_rows: dict[int, dict[str, dict]] = {}
        for side, run in schedule:
            repo = args.repo_a if side == "a" else args.repo_b
            module = load_measurement(repo)
            rows = measure_one(module, scenario, args.fixture)
            paired_rows.setdefault(run, {})[side] = rows[0]
        rows_a = [paired_rows[run]["a"] for run in range(args.runs)]
        rows_b = [paired_rows[run]["b"] for run in range(args.runs)]
        differences = [
            b["wall_ms"] - a["wall_ms"] for a, b in zip(rows_a, rows_b, strict=True)
        ]
        summaries[scenario] = {
            "a": rows_a,
            "b": rows_b,
            "difference_ms": differences,
            "bootstrap_95": paired_bootstrap(differences),
        }
    data = {
        "run_started_at": datetime.now(UTC).isoformat(),
        "fixture": args.fixture,
        "machine_id": platform.node(),
        "load_average_1_5_15": os.getloadavg(),
        "results": summaries,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
