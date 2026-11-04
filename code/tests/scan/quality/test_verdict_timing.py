"""Scan timing and memory on 400 generated Python files (slow).

Each measurement runs the scan in a fresh process and reports wall seconds and
peak memory (the process plus its children, since the quality pass uses a pool).
Compared on warm facts caches, best of ``RUNS``. The verdict-on bound (<= 1.5x of
the plain quality scan with 20 shown files) is asserted here. The "scan without
a verdict request is <= 5% slower and <= 1.5x memory than before the change"
bound needs the pre-change code: set ``VARDE_TIMING_BASELINE_SRC`` to the
``code/src`` of a pre-change checkout to assert it; the numbers print either way.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.build import build
from varde_code.parse import parse_source

FILES = 400
SHOWN = 20
RUNS = 5
VERDICT_WALL_BOUND = 1.5
PLAIN_WALL_BOUND = 1.05
PLAIN_MEMORY_BOUND = 1.5

_RUNNER = """
import json, resource, sys, time
from varde_code.scan import core
payload = json.loads(sys.argv[1])
started = time.perf_counter()
core.scan_repo(payload)
elapsed = time.perf_counter() - started
peak = max(
    resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
)
print(json.dumps({"wall": elapsed, "peak": peak}))
"""

pytestmark = pytest.mark.slow


def _source(index: int) -> str:
    body = "".join(
        f"    for price in prices:\n        if price > {j + index}:\n"
        f"            subtotal = subtotal + price * discount + {j}\n"
        for j in range(4)
    )
    wrap = (
        f"def wrap_{index}(prices, discount):\n"
        f"    return total_{index}(prices, discount)\n"
    )
    return (
        f"def total_{index}(prices, discount):\n    subtotal = 0\n{body}"
        f"    return subtotal\n\n\n{wrap}"
    )


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        cwd=root, check=True, capture_output=True,
    )  # fmt: skip


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    try:
        parse_source("python", "value\n")
    except RuntimeError as error:
        pytest.skip(f"tree-sitter grammar cache unavailable: {error}")
    root = tmp_path_factory.mktemp("timing") / "repo"
    (root / "pkg").mkdir(parents=True)
    for i in range(FILES):
        (root / "pkg" / f"mod_{i}.py").write_text(_source(i), encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base", "--no-verify")
    for i in range(SHOWN):
        with (root / "pkg" / f"mod_{i}.py").open("a", encoding="utf-8") as handle:
            handle.write("\nVALUE = 1\n")
    build(root, CodeExtractionProvider())
    return root


def _run_once(root: Path, extra: dict, src: str | None = None) -> dict:
    env = {**os.environ}
    if src:
        env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    payload = json.dumps({"repoRoot": str(root), **extra})
    out = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _RUNNER, payload],
        env=env, check=True, capture_output=True, text=True,
    )  # fmt: skip
    return json.loads(out.stdout.strip().splitlines()[-1])


def _best(root: Path, extra: dict, src: str | None = None) -> dict:
    _run_once(root, extra, src)  # warm the facts cache
    runs = [_run_once(root, extra, src) for _ in range(RUNS)]
    return {
        "wall": min(run["wall"] for run in runs),
        "peak": min(run["peak"] for run in runs),
    }


def test_verdict_on_costs_at_most_one_and_a_half_times_plain_scan(repo, capsys):
    plain = _best(repo, {})
    verdict = _best(repo, {"changedSince": "HEAD"})
    ratio = verdict["wall"] / plain["wall"]
    with capsys.disabled():
        print(
            f"\ntiming ({FILES} files, {SHOWN} shown): plain {plain['wall']:.2f}s "
            f"peak {plain['peak']}; verdict {verdict['wall']:.2f}s "
            f"peak {verdict['peak']}; ratio {ratio:.2f}"
        )
    assert ratio <= VERDICT_WALL_BOUND


def test_plain_scan_is_not_slower_than_before_the_change(repo, capsys):
    baseline = os.environ.get("VARDE_TIMING_BASELINE_SRC")
    if not baseline:
        pytest.skip("set VARDE_TIMING_BASELINE_SRC to a pre-change code/src")
    before = _best(repo, {}, baseline)
    after = _best(repo, {})
    wall, memory = after["wall"] / before["wall"], after["peak"] / before["peak"]
    with capsys.disabled():
        print(
            f"\nplain vs before ({FILES} files): before {before['wall']:.2f}s "
            f"peak {before['peak']}; after {after['wall']:.2f}s peak {after['peak']}; "
            f"wall x{wall:.3f} memory x{memory:.3f}"
        )
    assert wall <= PLAIN_WALL_BOUND
    assert memory <= PLAIN_MEMORY_BOUND
