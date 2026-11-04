#!/usr/bin/env python3
"""Profile opt-in hook spans; run the batch through toz/scripts/toz-perf/perf_run.py."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SIZES = (200, 65_536, 1_048_576)
PHASES = (
    "profile driver startup",
    "interpreter startup",
    "imports",
    "config load",
    "provider routing",
    "payload read",
    "project-root resolution",
    "payload parse",
    "payload shaping",
    "capture dispatch and setup",
    "hook classification and scope checks",
    "scope and readonly checks",
    "command scanning",
    "capture input encoding",
    "capture policy and profile setup",
    "hook redaction",
    "capture redaction",
    "chunking and preview",
    "metadata sanitization",
    "SQLite open and pragmas",
    "store transaction begin",
    "store metadata and records",
    "FTS5 write",
    "statistics write",
    "outcome event/note",
    "output",
    "unattributed work",
)
ALIASES = {name: name for name in PHASES}


def percentile(values: list[float], fraction: float) -> float:
    return sorted(values)[round((len(values) - 1) * fraction)]


def payload(size: int, shape: str) -> bytes:
    value = {
        "hook_event_name": "PostToolUse",
        "session_id": "bench",
        "tool_name": "Bash",
        "tool_input": {"command": "cat README.md"},
        "tool_response": {"stdout": "", "stderr": "", "interrupted": False},
    }
    content = "x" * size
    if shape == "command":
        value["tool_input"]["command"] = content
    else:
        value["tool_response"]["stdout"] = content
    return json.dumps(value, separators=(",", ":")).encode()


def run_hook(
    data: bytes,
    env: dict[str, str],
    launcher: Path,
    driver_startup_ms: float,
    startup_ms: float,
    imports_ms: float,
) -> tuple[float, dict[str, float]]:
    driver = (
        "import subprocess,sys; "
        "p=subprocess.run([sys.argv[1],'hook','post-tool-use','--harness','claude'], "
        "input=sys.stdin.buffer.read(),stdout=subprocess.PIPE,stderr=subprocess.PIPE); "
        "sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr); "
        "raise SystemExit(p.returncode)"
    )
    started = time.perf_counter_ns()
    proc = subprocess.run(  # noqa: S603 - Benchmark runs the local hook process with controlled arguments.
        [
            sys.executable,
            "-c",
            driver,
            str(launcher),
        ],
        input=data,
        capture_output=True,
        env=env,
        cwd=env["VARDE_PROFILE_CWD"],
        check=False,
    )
    wall = (time.perf_counter_ns() - started) / 1e6
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode(errors="replace"))
    phases: dict[str, float] = {}
    for line in proc.stderr.decode(errors="replace").splitlines():
        if not line.startswith("PHASE_TRACE|"):
            continue
        _, name, ns = line.split("|", 2)
        phase = ALIASES.get(name)
        if phase is None:
            raise RuntimeError(f"unaliased phase span: {name}")
        phases[phase] = phases.get(phase, 0.0) + int(ns) / 1e6
    traced = sum(phases.values())
    reference_ms = driver_startup_ms + startup_ms + imports_ms
    available_reference_ms = max(0.0, wall - traced)
    reference_scale = (
        min(1.0, available_reference_ms / reference_ms) if reference_ms else 1.0
    )
    phases["profile driver startup"] = driver_startup_ms * reference_scale
    phases["interpreter startup"] = startup_ms * reference_scale
    phases["imports"] = imports_ms * reference_scale
    references = (
        phases["profile driver startup"]
        + phases["interpreter startup"]
        + phases["imports"]
    )
    phases["unattributed work"] = max(0.0, wall - traced - references)
    if abs(sum(phases.values()) - wall) > max(2.0, wall * 0.05):
        raise RuntimeError(
            f"phase durations do not reconcile: sum={sum(phases.values()):.3f}, "
            f"wall={wall:.3f} ms; "
            f"phases={sorted(phases.items())}"
        )
    return wall, phases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--shape", choices=("output", "command"), default="output")
    parser.add_argument("--size", type=int, choices=SIZES)
    parser.add_argument(
        "--launcher",
        type=Path,
        default=Path("/Users/alec/source/varde/.venv/bin/varde-toz"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "toz/tests/fixtures/phases-v2.json",
    )
    args = parser.parse_args()
    if args.validate:
        _validate_fixture(args.output)
        return 0
    if args.runs < 30:
        parser.error("--runs must be at least 30")

    with tempfile.TemporaryDirectory(prefix="toz-phase-") as temp:
        fixture = Path(temp)
        home, config, store, cwd = (
            fixture / part for part in ("home", "config", "toz", "repo")
        )
        for directory in (home, config, store, cwd):
            directory.mkdir(parents=True, exist_ok=True)
        (config / "config.toml").write_text(
            '[hooks.post_tool_use]\nproviders=["capture"]\n'
            '[hooks.session_start]\nproviders=["toz_note"]\n'
            f'[instructions]\ntargets = ["{cwd / "instructions.md"}"]\n'
        )
        (cwd / "instructions.md").write_text("fixture instruction target\n")
        env = os.environ.copy()
        source_path = str(ROOT / "toz/src")
        env.update(
            {
                "HOME": str(home),
                "VARDE_CONFIG_DIR": str(config),
                "VARDE_TOZ_CONFIG_DIR": str(store),
                "TMPDIR": str(fixture),
                "PYTHONPATH": source_path + os.pathsep + env.get("PYTHONPATH", ""),
                "VARDE_TOZ_PHASE_TRACE": "1",
                "VARDE_PROFILE_CWD": str(cwd),
            }
        )
        from time import perf_counter_ns

        startup_samples = []
        for _ in range(args.runs):
            before = perf_counter_ns()
            subprocess.run(
                [sys.executable, "-c", "pass"], check=True, stdout=subprocess.DEVNULL
            )
            startup_samples.append((perf_counter_ns() - before) / 1e6)
        startup_ms = statistics.median(startup_samples)
        launcher_help_samples = []
        for _ in range(args.runs):
            before = perf_counter_ns()
            subprocess.run(  # noqa: S603 - Benchmark runs the local CLI with controlled arguments.
                [str(args.launcher), "--help"],
                check=True,
                stdout=subprocess.DEVNULL,
                cwd=cwd,
                env=env,
            )
            launcher_help_samples.append((perf_counter_ns() - before) / 1e6)
        imports_ms = max(0.0, statistics.median(launcher_help_samples) - startup_ms)

        sizes = (
            (args.size,)
            if args.size is not None
            else (SIZES if args.shape == "output" else (1_048_576,))
        )
        rows = []
        for size in sizes:
            walls = []
            phase_samples = {phase: [] for phase in PHASES}
            data = payload(size, args.shape)
            for _ in range(args.runs):
                wall, phases = run_hook(
                    data, env, args.launcher, startup_ms, startup_ms, imports_ms
                )
                walls.append(round(wall, 3))
                for phase in PHASES:
                    phase_samples[phase].append(round(phases.get(phase, 0.0), 3))
            rows.append(
                {
                    "size": size,
                    "shape": args.shape,
                    "wall": {
                        "p50_ms": round(statistics.median(walls), 3),
                        "p95_ms": round(percentile(walls, 0.95), 3),
                        "samples_ms": walls,
                    },
                    "phases": {
                        phase: {
                            "p50_ms": round(statistics.median(values), 3),
                            "samples_ms": values,
                        }
                        for phase, values in phase_samples.items()
                    },
                }
            )
        result = {
            "runs": args.runs,
            "shape": args.shape,
            "phases": list(PHASES),
            "rows": rows,
            "method": (
                "all wall and per-phase samples retained; spans are disjoint; "
                "run through toz/scripts/toz-perf/perf_run.py under ordinary load"
            ),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    return 0


def _validate_fixture(path: Path) -> None:
    data = json.loads(path.read_text())
    runs = data["measurement"]["runs_per_phase_row"]
    if runs < 30 or len(data["rows"]) != 4:
        raise AssertionError("expected at least 30 runs and four rows")
    for row in data["rows"]:
        if len(row["wall"]["samples_ms"]) != runs:
            raise AssertionError("wall sample count does not match runs")
        if set(row["phases"]) != set(data["phases"]):
            raise AssertionError("phase names do not match fixture")
        for phase in data["phases"]:
            if len(row["phases"][phase]["samples_ms"]) != runs:
                raise AssertionError(f"sample count does not match runs for {phase}")
        for index, wall in enumerate(row["wall"]["samples_ms"]):
            phase_total = sum(
                row["phases"][phase]["samples_ms"][index] for phase in data["phases"]
            )
            if abs(phase_total - wall) > max(2.0, wall * 0.05):
                raise AssertionError("phase durations do not reconcile")
            if row["phases"]["unattributed work"]["samples_ms"][index] >= wall * 0.1:
                raise AssertionError("unattributed work exceeds 10% of wall time")


if __name__ == "__main__":
    raise SystemExit(main())
