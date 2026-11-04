#!/usr/bin/env python3
"""Run and record every measured sample under the measurement lock."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOCKER = ROOT / "dev/scripts/with-lock.sh"


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * fraction + 0.999999) - 1))
    return ordered[index]


def run_locked(command: list[str], runs: int) -> dict:
    lock_started = time.perf_counter()
    load_before = os.getloadavg()
    samples = []
    for _ in range(runs):
        started = time.perf_counter_ns()
        result = subprocess.run(  # noqa: S603 - Benchmark deliberately runs the operator-supplied command.
            command, stdout=subprocess.DEVNULL, check=False
        )
        if result.returncode:
            raise RuntimeError(
                f"measured command exited with status {result.returncode}"
            )
        samples.append(round((time.perf_counter_ns() - started) / 1e6, 3))
    load_after = os.getloadavg()
    lock_hold_s = round(time.perf_counter() - lock_started, 6)
    return {
        "samples": samples,
        "wall_ms": {"p50": percentile(samples, 0.5), "p95": percentile(samples, 0.95)},
        "load_before": load_before,
        "load_after": load_after,
        "lock_hold_s": lock_hold_s,
    }


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock-dir", default="/Users/alec/source/.varde-measure.lock")
    parser.add_argument("--lock-timeout", type=int)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = (
        args.command[1:] if args.command and args.command[0] == "--" else args.command
    )
    if (
        not command
        or args.runs < 1
        or (args.lock_timeout is not None and args.lock_timeout < 0)
    ):
        parser.error(
            "command, positive runs, and non-negative lock timeout are required"
        )
    return args, command


def main() -> int:
    args, command = parse_args()
    env = {**os.environ, "VARDE_LOCK_DIR": args.lock_dir}
    if args.lock_timeout is not None:
        env["VARDE_LOCK_TIMEOUT_S"] = str(args.lock_timeout)
    # Invoke this module's worker directly while with-lock.sh owns the lock.
    worker = [
        sys.executable,
        "-c",
        (
            "import json,sys; sys.path.insert(0,sys.argv[1]); import perf_run; "
            "print(json.dumps(perf_run.run_locked(sys.argv[3:],int(sys.argv[2]))))"
        ),
        str(Path(__file__).resolve().parent),
        str(args.runs),
        *command,
    ]
    result = subprocess.run(  # noqa: S603 - Benchmark deliberately runs the operator-supplied command.
        [str(LOCKER), *worker], env=env, capture_output=True, text=True, check=False
    )
    if result.returncode:
        print(result.stderr, file=sys.stderr, end="")
        return result.returncode
    attempt = json.loads(result.stdout.strip().splitlines()[-1])
    attempt["attempt"] = 1
    print(
        json.dumps(
            {
                "status": "ok",
                "command": shlex.join(command),
                "launcher": command[0],
                "lock": args.lock_dir,
                "attempts": [attempt],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
