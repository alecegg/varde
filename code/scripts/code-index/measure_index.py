#!/usr/bin/env python3
"""Measure cold, no-change refresh, and one-file edit index costs."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "code/tests/fixtures"
LOCK = Path("/Users/alec/source/.varde-measure.lock")
OUT = Path(__file__).resolve().parent / "results/index-speed.json"
SCENARIOS = ("cold", "no_change", "edit1")


def loadavg() -> list[float]:
    return list(os.getloadavg())


def ioreg_bytes() -> int:
    result = subprocess.run(
        ["ioreg", "-c", "IOBlockStorageDriver", "-r", "-w0"],  # noqa: S607 - Queries the platform ioreg utility available on macOS.
        check=True,
        capture_output=True,
        text=True,
    )
    values = []
    for line in result.stdout.splitlines():
        if '"Bytes (Write)"=' in line:
            with contextlib.suppress(ValueError):
                values.append(
                    int(line.split('"Bytes (Write)"=', 1)[1].split(",", 1)[0].strip())
                )
    if not values:
        raise RuntimeError("ioreg did not report Bytes (Write)")
    return sum(values)


def python_call(action: str, repo: Path, env: dict[str, str]) -> None:
    code = r"""import sys
from pathlib import Path
from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index import build, incremental
repo=Path(sys.argv[1])
action=sys.argv[2]
(build.build if action=="cold" else incremental.refresh)(repo,CodeExtractionProvider())
"""
    subprocess.run(  # noqa: S603 - Runs the measured indexing command with constructed arguments.
        [sys.executable, "-c", code, str(repo), action],
        cwd=ROOT,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )


def execute(scenario: str, runs: int) -> list[dict]:
    samples = []
    for _ in range(runs):
        with tempfile.TemporaryDirectory(prefix="varde-index-measure-") as temp:
            base = Path(temp)
            repo = base / "repo"
            shutil.copytree(FIXTURES / "repos/tiny", repo)
            (repo / "README.md").unlink()
            config = base / "config"
            home = base / "home"
            config.mkdir()
            home.mkdir()
            env = os.environ.copy()
            env.update(
                {
                    "VARDE_CONFIG_DIR": str(config),
                    "VARDE_TOZ_CONFIG_DIR": str(config),
                    "HOME": str(home),
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": str(ROOT / "code/src")
                    + os.pathsep
                    + str(ROOT / "core/src"),
                }
            )
            if scenario != "cold":
                python_call("cold", repo, env)
            if scenario == "edit1":
                source = repo / "src/main.py"
                source.write_bytes(
                    source.read_bytes() + b"\n# one-file benchmark edit\n"
                )
            idle_before = ioreg_bytes()
            idle_load = loadavg()
            subprocess.run(
                [sys.executable, "-c", "pass"],
                check=True,
                env=env,
                stdout=subprocess.DEVNULL,
            )
            idle_after = ioreg_bytes()
            before = ioreg_bytes()
            started = time.perf_counter_ns()
            python_call("cold" if scenario == "cold" else "refresh", repo, env)
            wall_ms = (time.perf_counter_ns() - started) / 1_000_000
            after = ioreg_bytes()
            samples.append(
                {
                    "wall_ms": wall_ms,
                    "device_write_bytes": max(after - before, 0),
                    "paired_idle_write_bytes": max(idle_after - idle_before, 0),
                    "load_average_1_5_15": idle_load,
                }
            )
    return samples


def median(samples: list[dict], key: str) -> float:
    return statistics.median(row[key] for row in samples)


def net_write_median(samples: list[dict]) -> float:
    return statistics.median(
        max(row["device_write_bytes"] - row["paired_idle_write_bytes"], 0)
        for row in samples
    )


def validate(data: dict) -> list[str]:
    errors = []
    for scenario in SCENARIOS:
        if scenario not in data.get("results", {}):
            errors.append(f"missing scenario {scenario}")
            continue
        rows = data["results"][scenario].get("python", [])
        if len(rows) < 30:
            errors.append(f"{scenario}/python: need >=30 retained runs")
        errors.extend(
            f"{scenario}/python: incomplete run"
            for row in rows
            if not all(
                k in row
                for k in (
                    "wall_ms",
                    "device_write_bytes",
                    "paired_idle_write_bytes",
                    "load_average_1_5_15",
                )
            )
        )
    if errors:
        return errors
    py_nochange = data["results"]["no_change"]["python"]
    py_edit = data["results"]["edit1"]["python"]
    if net_write_median(py_nochange) > 1_000_000:
        errors.append("no-change net writes exceed 1,000,000 B")
    if not py_edit:
        errors.append("edit1/python: no retained runs")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", type=Path)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="exercise one cold/no-change/edit path without saving results",
    )
    args = parser.parse_args()
    if args.check:
        data = json.loads(args.check.read_text())
        errors = validate(data)
        print("check: " + ("PASS" if not errors else "FAIL: " + "; ".join(errors)))
        return 0 if not errors else 1
    if args.runs < 1 or (not args.dry_run and args.runs < 30):
        parser.error(
            "measurement requires --runs >=30 (dry-run accepts smaller counts)"
        )
    if not LOCK.is_dir():
        raise SystemExit(f"measurement lock is not held: {LOCK}")
    count = 1 if args.dry_run else args.runs
    results = {scenario: {} for scenario in SCENARIOS}
    for scenario in SCENARIOS:
        rows = execute(scenario, count)
        results[scenario]["python"] = rows
        print(f"{scenario}/python: N={count} wall p50={median(rows, 'wall_ms'):.2f} ms")
    if args.dry_run:
        print("dry-run: PASS (results not saved)")
        return 0
    data = {
        "run_started_at": datetime.now(UTC).isoformat(),
        "measurement": {
            "runs_per_scenario": args.runs,
            "ioreg_source": "IOBlockStorageDriver Bytes (Write)",
            "idle_pair": (
                "ioreg delta around an immediate no-op subprocess before the "
                "measured call; no sleep or quiet gating"
            ),
            "fixture": "code/tests/fixtures/repos/tiny",
        },
        "results": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    errors = validate(data)
    print("thresholds: " + ("PASS" if not errors else "FAIL: " + "; ".join(errors)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
