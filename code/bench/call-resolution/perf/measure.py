"""Measure fast-path wall time and peak RSS on the tiny and medium fixtures.

Scenarios, each in a fresh child process per run: ``cold`` (index build),
``no_change`` (incremental refresh over a built index), ``quality_pass``
(``run_quality_pass`` over a built index). Peak RSS comes from ``wait4`` of the
child. Usage (repo root):

    uv run python code/bench/call-resolution/perf/measure.py --runs 7 \
        --out baseline.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stats

ROOT = Path(__file__).resolve().parents[4]
FIXTURE_SCRIPT = ROOT / "code/scripts/code-index/make_medium_fixture.py"
SCENARIOS = ("cold", "no_change", "quality_pass")
CHILD = {
    "cold": "from varde_code.extract.provider import CodeExtractionProvider\n"
    "from varde_code.index import build\n"
    "build.build(Path(sys.argv[1]), CodeExtractionProvider())",
    "no_change": "from varde_code.extract.provider import CodeExtractionProvider\n"
    "from varde_code.index import incremental\n"
    "incremental.refresh(Path(sys.argv[1]), CodeExtractionProvider())",
    "quality_pass": "from varde_code.quality_pass import run_quality_pass\n"
    "run_quality_pass(Path(sys.argv[1]))",
}


def child_command(scenario: str, repo: Path) -> list[str]:
    code = "import sys\nfrom pathlib import Path\n" + CHILD[scenario]
    return [sys.executable, "-c", code, str(repo)]


def child_env(base: Path) -> dict[str, str]:
    env = os.environ.copy()
    config = base / "config"
    home = base / "home"
    config.mkdir()
    home.mkdir()
    env.update(
        {
            "VARDE_CONFIG_DIR": str(config),
            "VARDE_TOZ_CONFIG_DIR": str(config),
            "HOME": str(home),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ROOT / "code/src") + os.pathsep + str(ROOT / "core/src"),
        }
    )
    return env


def run_measured(command: list[str], env: dict[str, str]) -> dict:
    started = time.perf_counter_ns()
    proc = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.DEVNULL)  # noqa: S603
    _, status, usage = os.wait4(proc.pid, 0)
    wall_ms = (time.perf_counter_ns() - started) / 1_000_000
    proc.returncode = os.waitstatus_to_exitcode(status)
    if proc.returncode:
        raise RuntimeError(f"child failed ({proc.returncode}): {command[-1]}")
    return {
        "wall_ms": wall_ms,
        "peak_rss_bytes": stats.rss_bytes(usage.ru_maxrss, sys.platform),
        "load_average_1_5_15": list(os.getloadavg()),
    }


def prepare_fixture(kind: str, destination: Path) -> Path:
    if kind == "tiny":
        shutil.copytree(ROOT / "code/tests/fixtures/repos/tiny", destination)
        (destination / "README.md").unlink()
        return destination
    subprocess.run(  # noqa: S603
        [sys.executable, str(FIXTURE_SCRIPT), str(destination)],
        check=True,
        capture_output=True,
    )
    return destination


def one_run(kind: str, scenario: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="varde-perf-") as temp:
        base = Path(temp)
        repo = prepare_fixture(kind, base / "repo")
        env = child_env(base)
        if scenario != "cold":
            subprocess.run(  # noqa: S603
                child_command("cold", repo), cwd=ROOT, env=env, check=True
            )
        return run_measured(child_command(scenario, repo), env)


def measure(fixtures: list[str], runs: int) -> dict:
    results: dict[str, dict] = {}
    commands = {s: child_command(s, Path("<repo>")) for s in SCENARIOS}
    for kind in fixtures:
        results[kind] = {}
        for scenario in SCENARIOS:
            one_run(kind, scenario)  # discarded warm-up
            rows = [one_run(kind, scenario) for _ in range(runs)]
            results[kind][scenario] = {**stats.summarize(rows), "samples": rows}
    return {
        "run_started_at": datetime.now(UTC).isoformat(),
        "machine": platform.node(),
        "python": sys.version.split()[0],
        "load_average_1_5_15": list(os.getloadavg()),
        "runs_per_scenario": runs,
        "commands": {s: c[:2] + ["<code>"] + c[3:] for s, c in commands.items()},
        "scenario_code": {s: CHILD[s] for s in SCENARIOS},
        "command_line": sys.argv,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--fixture", choices=("tiny", "medium", "both"), default="both")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.runs < 5:
        parser.error("--runs must be >=5")
    fixtures = ["tiny", "medium"] if args.fixture == "both" else [args.fixture]
    data = measure(fixtures, args.runs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
