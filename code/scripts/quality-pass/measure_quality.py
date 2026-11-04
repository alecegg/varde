#!/usr/bin/env python3
"""Measure quality-pass latency against the fast index baseline (PA7-PA9).

Sides of the interleaved A/B, each run in one fresh child process:
- A: the fast index step alone (cold build, or the incremental refresh).
- B: the same index step followed by ``run_quality_pass``.

The child measures the index step and the pass stage with
``time.perf_counter_ns`` inside itself and prints ``index_ms`` and ``pass_ms``,
so the paired difference between the sides is the pass work alone: side A never
pays a second interpreter start or a quality-package import that side B pays.
The parent measures the whole child as ``wall_ms``; ``startup_ms`` is
``wall_ms`` minus the in-child work, and the per-sample startup is recorded so
its size is visible. Both sides run on the same machine, on one freshly copied
fixture per sample, alternating order per run. Each JSON row keeps wall time,
in-child work, index and pass time, startup cost, device write bytes, the
paired idle write delta, the load average and, on side B, the pass summary
counts.

The ``edit1_quality`` scenario appends a comment line to the leaf file, so only
that file's facts and measures change. The ``edit_hub_quality`` scenario
appends a new function to the hub file (the file with the largest transitive
set of files that import or mention it), so the file's exported function ids
change and the reverse closure of its importers is invalidated. Hub and leaf
are picked from import-like references (a line starting with an import keyword)
among paths that are not test, generated or vendored by name: that name filter
stands in for the pass's path classes, which are only known after an index
build, so ``hub``/``leaf``, their closure sizes and a warning when the hub
closure is not larger than the leaf's are all written to the results. The hub
edit is also flagged when side B recomputes no more files for it than for the
leaf edit.

The ratio proposals of ``quality-pass-architecture.md`` v2 section 6 are read
from the saved output:
- PA7 ``k`` = ``targets[].scenarios.cold_quality.ratio_median`` (quality pass
  over cold index time).
- PA8 ``j`` = ``targets[].scenarios.no_change_quality.ratio_median`` (quality
  pass over the incremental refresh time, which includes ``ensure_fresh``).
- PA9 ``m`` = the ``edit1_quality`` and ``edit_hub_quality``
  ``ratio_median`` values (quality pass over the one-file refresh), with the
  recomputed-file bound from ``b_pass_summary_median`` in the same rows.

``ratio_median`` is the median of the per-pair ``pass_ms / index_ms`` ratios and
``ratio_bootstrap_95`` is the 2.5/97.5 percentile bootstrap interval of that
same median, so point estimate and interval describe one statistic.
``bootstrap_95`` is the interval of the mean of the paired ``work_ms``
differences and is labelled as such. ``proposed_ratios`` reports k, j and both
m values per target and per size class (tiny at most 10 source files, medium at
most 500, large above, from the target's own file count). They are proposals
only: the script asserts no wall-clock target.

Usage: hold the measurement lock (``dev/scripts/with-lock.sh``, honoured
through ``VARDE_LOCK_DIR``), then run this script from the repository root, for
example::

    dev/scripts/with-lock.sh \
        uv run python code/scripts/quality-pass/measure_quality.py \
        --fixture both --repo ../varde --out "$TMPDIR/quality-pass.json"

``--fixture tiny``, ``medium`` or ``both``; ``--repo`` is repeatable and one
discarded warm-up pair per scenario runs before the retained runs
(``--warmup``). Repositories are never fetched from the network: ``--repo``
takes local checkouts and the script only copies them (without ``.git``,
``node_modules``, ``.venv`` and ``__pycache__``) into a temporary directory per
sample. ``--out`` is required for a measurement run and is refused under any
repository's ``results/`` directory.
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import os
import platform
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "code/tests/fixtures"
HARNESS_SCRIPT = REPO_ROOT / "code/scripts/code-index/measure_index_ab.py"
INDEX_SCRIPT = REPO_ROOT / "code/scripts/code-index/measure_index.py"
SCENARIOS = ("cold_quality", "no_change_quality", "edit1_quality", "edit_hub_quality")
EDIT_SCENARIOS = frozenset({"edit1_quality", "edit_hub_quality"})
COPY_IGNORE = (".git", "node_modules", ".venv", "__pycache__")
TINY_MAX_FILES = 10
MEDIUM_MAX_FILES = 500
SOURCE_SUFFIXES = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".cxx",
        ".go",
        ".hpp",
        ".java",
        ".js",
        ".jsx",
        ".py",
        ".rs",
        ".ts",
        ".tsx",
    }
)
EXCLUDED_DIRS = frozenset(
    {
        "fixtures",
        "generated",
        "golden",
        "goldens",
        "node_modules",
        "test",
        "tests",
        "testing",
        "third-party",
        "third_party",
        "vendor",
    }
)
EXCLUDED_NAME_MARKERS = (
    ".designer.cs",
    ".g.cs",
    ".min.",
    "_generated.",
    "_pb2.",
    "_test.",
    "test_",
)
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_IMPORT_LINE = re.compile(
    r"^\s*#?\s*(?:extern|from|import|include|mod|require|use|using)\b"
)

_COMMENT_MARKER = {".py": "#"}

# Appending one function changes the file's exported function ids, which is what
# makes an importers' resolution digest and its reverse closure invalidate.
FUNCTION_SNIPPETS = {
    ".c": "\nstatic int qs_hub_probe(void) { return 1; }\n",
    ".cc": "\nstatic int qs_hub_probe(void) { return 1; }\n",
    ".cpp": "\nstatic int qs_hub_probe(void) { return 1; }\n",
    ".cs": (
        "\ninternal static class QsHubProbe {\n"
        "    internal static int Value() { return 1; }\n}\n"
    ),
    ".cxx": "\nstatic int qs_hub_probe(void) { return 1; }\n",
    ".go": "\nfunc qsHubProbe() int {\n\treturn 1\n}\n",
    ".hpp": "\nstatic int qs_hub_probe(void) { return 1; }\n",
    ".java": "\nclass QsHubProbe {\n  static int value() { return 1; }\n}\n",
    ".js": "\nexport function qsHubProbe() {\n  return 1;\n}\n",
    ".jsx": "\nexport function qsHubProbe() {\n  return 1;\n}\n",
    ".py": "\n\ndef qs_hub_probe():\n    return 1\n",
    ".rs": "\nfn qs_hub_probe() -> i32 {\n    1\n}\n",
    ".ts": "\nexport function qsHubProbe(): number {\n  return 1;\n}\n",
    ".tsx": "\nexport function qsHubProbe(): number {\n  return 1;\n}\n",
}

CHILD_CODE = r"""import json
import sys
import time
from pathlib import Path
from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index import build, incremental

repo = Path(sys.argv[1])
action = sys.argv[2]
mode = sys.argv[3]
started = time.perf_counter_ns()
(build.build if action == "cold" else incremental.refresh)(
    repo, CodeExtractionProvider()
)
index_ms = (time.perf_counter_ns() - started) / 1_000_000
pass_ms = None
summary = None
if mode == "pass":
    started = time.perf_counter_ns()
    from varde_code.quality_pass import run_quality_pass

    result = run_quality_pass(repo)
    pass_ms = (time.perf_counter_ns() - started) / 1_000_000
    summary = {
        "file_count": result.file_count,
        "cached": result.cached,
        "facts_recomputed": len(result.facts_recomputed),
        "edges_recomputed": len(result.edges_recomputed),
        "measures_recomputed": len(result.measures_recomputed),
        "facts_reused": result.facts_reused,
        "edges_reused": result.edges_reused,
        "measures_reused": result.measures_reused,
    }
print(json.dumps({"index_ms": index_ms, "pass_ms": pass_ms, "pass_summary": summary}))
"""

MeasureFn = Callable[[str, str, "Target"], dict]


@dataclass(frozen=True)
class Target:
    """One repository to measure, with the edit files picked from its tree."""

    name: str
    kind: str
    size_class: str
    path: Path
    file_count: int = 0
    hub: str | None = None
    leaf: str | None = None
    hub_closure_size: int = 0
    leaf_closure_size: int = 0
    warnings: tuple[str, ...] = ()


@functools.cache
def _load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_harness():
    """The reusable A/B helpers of the fast-index harness (read-only)."""
    return _load_script(HARNESS_SCRIPT, "measure_index_ab")


def load_index_scenarios():
    """The fast-index scenario helpers (write bytes, load average, median)."""
    return _load_script(INDEX_SCRIPT, "measure_index_quality")


def lock_path(env: Mapping[str, str] | None = None) -> Path:
    """The measurement lock directory, shared with ``with-lock.sh``."""
    return load_harness().lock_path(env)


def output_path(path: Path, repos: Sequence[Path]) -> Path:
    """Resolve ``path``, refusing any repository ``results/`` destination."""
    resolved = path
    for repo in repos:
        resolved = load_harness().output_path(resolved, repo, repo)
    return resolved


def _unique_names(repos: Sequence[Path]) -> list[str]:
    """Basenames with a numeric suffix when two repositories share one."""
    seen: dict[str, int] = {}
    names = []
    for repo in repos:
        base = repo.name or "repo"
        seen[base] = seen.get(base, 0) + 1
        names.append(base if seen[base] == 1 else f"{base}-{seen[base]}")
    return names


def resolve_targets(
    fixture: str, repos: Sequence[Path], medium_root: Path
) -> list[Target]:
    """Build the fixture targets plus one target per ``--repo``."""
    targets = []
    if fixture in ("tiny", "both"):
        targets.append(Target("tiny", "tiny", "", FIXTURES / "repos/tiny"))
    if fixture in ("medium", "both"):
        path = load_harness().make_medium_fixture(medium_root)
        targets.append(Target("medium", "medium", "", path))
    names = _unique_names(repos)
    targets.extend(
        Target(name, "repo", "", repo) for name, repo in zip(names, repos, strict=True)
    )
    return targets


def _read_text(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8", "replace")
    except OSError:
        return ""


def _files(root: Path) -> list[Path]:
    ignored = set(COPY_IGNORE)
    found = (
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in SOURCE_SUFFIXES
        and not ignored.intersection(path.parts)
    )
    return sorted(found, key=lambda path: path.as_posix())


def _is_candidate(path: Path) -> bool:
    """True for paths not named like tests, generated code or vendored code."""
    if any(part.lower() in EXCLUDED_DIRS for part in path.parts[:-1]):
        return False
    name = path.name.lower()
    return not (
        name.startswith("test_")
        or any(marker in name for marker in EXCLUDED_NAME_MARKERS)
    )


def _import_tokens(text: str) -> set[str]:
    """Tokens on lines that look like an import, include or using statement."""
    tokens: set[str] = set()
    for line in text.splitlines():
        if _IMPORT_LINE.match(line):
            tokens.update(_TOKEN.findall(line))
    return tokens


def _direct_references(paths: Sequence[Path]) -> dict[Path, set[Path]]:
    """Each file's stem maps to the other files that import or mention it."""
    by_token: dict[str, set[Path]] = {}
    for path in paths:
        for token in _import_tokens(_read_text(path)):
            by_token.setdefault(token, set()).add(path)
    return {
        path: {other for other in by_token.get(path.stem, ()) if other != path}
        for path in paths
    }


def reverse_closure_sizes(paths: Sequence[Path]) -> dict[Path, int]:
    """Count, per file, the files whose reference chain reaches it."""
    references = _direct_references(paths)
    index = {path: position for position, path in enumerate(paths)}
    ancestors = dict.fromkeys(paths, 0)
    for _ in range(len(paths)):
        changed = False
        for candidate in paths:
            bits = ancestors[candidate]
            for referrer in references[candidate]:
                bits |= (1 << index[referrer]) | ancestors[referrer]
            if bits != ancestors[candidate]:
                ancestors[candidate] = bits
                changed = True
        if not changed:
            break
    return {path: ancestors[path].bit_count() for path in paths}


def size_class_for(file_count: int) -> str:
    """Repository size class from its source file count."""
    if file_count <= TINY_MAX_FILES:
        return "tiny"
    if file_count <= MEDIUM_MAX_FILES:
        return "medium"
    return "large"


def select_edit_files(target: Target) -> Target:
    """Attach the hub (largest reverse closure) and the leaf file."""
    all_files = _files(target.path)
    if not all_files:
        return replace(target, size_class="unknown", warnings=("no_source_files",))
    candidates = [path for path in all_files if _is_candidate(path)] or all_files
    sizes = reverse_closure_sizes(candidates)
    hub = min(candidates, key=lambda path: (-sizes[path], path.as_posix()))
    leaf = min(candidates, key=lambda path: (sizes[path], path.as_posix()))
    warnings = ()
    if sizes[hub] <= sizes[leaf]:
        warnings = ("hub_closure_no_larger_than_leaf",)
    return replace(
        target,
        size_class=size_class_for(len(all_files)),
        file_count=len(all_files),
        hub=hub.relative_to(target.path).as_posix(),
        leaf=leaf.relative_to(target.path).as_posix(),
        hub_closure_size=sizes[hub],
        leaf_closure_size=sizes[leaf],
        warnings=warnings,
    )


def edit_marker(path: Path) -> str:
    """The line-comment marker for the file's language."""
    return _COMMENT_MARKER.get(path.suffix, "//")


def apply_edit(repo: Path, target: Target, scenario: str) -> None:
    """Edit the leaf with a comment or the hub with a new function."""
    relative = target.hub if scenario == "edit_hub_quality" else target.leaf
    if relative is None:
        raise SystemExit(f"no edit candidate for target {target.name}")
    path = repo / relative
    if scenario == "edit_hub_quality":
        addition = FUNCTION_SNIPPETS.get(path.suffix)
        if addition is None:
            raise SystemExit(f"no hub edit snippet for {path.suffix}")
    else:
        addition = f"\n{edit_marker(path)} one-file benchmark edit\n"
    path.write_bytes(path.read_bytes() + addition.encode("utf-8"))


def _child_env(base: Path) -> dict[str, str]:
    """Fresh isolated config, home and data dirs plus this checkout's source."""
    config = base / "config"
    home = base / "home"
    xdg_config = base / "xdg-config"
    xdg_data = base / "xdg-data"
    for directory in (config, home, xdg_config, xdg_data):
        directory.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "VARDE_CONFIG_DIR": str(config),
            "VARDE_TOZ_CONFIG_DIR": str(config),
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(xdg_config),
            "XDG_DATA_HOME": str(xdg_data),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join(
                [str(REPO_ROOT / "code/src"), str(REPO_ROOT / "core/src")]
            ),
        }
    )
    return env


def _run_child(action: str, mode: str, repo: Path, env: dict[str, str]) -> dict:
    """Run the index step and, in the same process, the optional pass stage."""
    result = subprocess.run(  # noqa: S603 - Runs the measured quality command with constructed arguments.
        [sys.executable, "-c", CHILD_CODE, str(repo), action, mode],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("measurement child returned no summary")
    return json.loads(lines[-1])


def _warm_up(repo: Path, target: Target, scenario: str, side: str, env: dict) -> None:
    """Prepare the state both sides must share before the timed step."""
    if scenario == "cold_quality":
        return
    _run_child("cold", "pass" if side == "b" else "index", repo, env)
    if scenario in EDIT_SCENARIOS:
        apply_edit(repo, target, scenario)


def measure_side(scenario: str, side: str, target: Target) -> dict:
    """Run one interleaved sample of one scenario and side."""
    index_module = load_index_scenarios()
    with tempfile.TemporaryDirectory(prefix="varde-quality-measure-") as temp:
        base = Path(temp)
        repo = base / "repo"
        shutil.copytree(
            target.path,
            repo,
            symlinks=True,
            ignore=shutil.ignore_patterns(*COPY_IGNORE),
        )
        env = _child_env(base)
        _warm_up(repo, target, scenario, side, env)
        idle_before = index_module.ioreg_bytes()
        load = index_module.loadavg()
        subprocess.run(
            [sys.executable, "-c", "pass"],
            check=True,
            env=env,
            stdout=subprocess.DEVNULL,
        )
        idle_after = index_module.ioreg_bytes()
        before = index_module.ioreg_bytes()
        started = time.perf_counter_ns()
        child = _run_child(
            "cold" if scenario == "cold_quality" else "refresh",
            "pass" if side == "b" else "index",
            repo,
            env,
        )
        wall_ms = (time.perf_counter_ns() - started) / 1_000_000
        after = index_module.ioreg_bytes()
    work_ms = child["index_ms"] + (child["pass_ms"] or 0.0)
    return {
        "wall_ms": wall_ms,
        "work_ms": work_ms,
        "index_ms": child["index_ms"],
        "pass_ms": child["pass_ms"],
        "startup_ms": max(wall_ms - work_ms, 0.0),
        "device_write_bytes": max(after - before, 0),
        "paired_idle_write_bytes": max(idle_after - idle_before, 0),
        "load_average_1_5_15": load,
        "pass_summary": child["pass_summary"],
    }


def _median_int(values: Sequence[int]) -> int:
    return int(statistics.median(values)) if values else 0


def _pass_medians(rows: Sequence[dict]) -> dict:
    keys = (
        "file_count",
        "facts_recomputed",
        "edges_recomputed",
        "measures_recomputed",
        "facts_reused",
        "edges_reused",
        "measures_reused",
    )
    summaries = [row["pass_summary"] for row in rows if row.get("pass_summary")]
    return {key: _median_int([int(item[key]) for item in summaries]) for key in keys}


def paired_median_bootstrap(values: Sequence[float], *, samples: int = 2000) -> list:
    """2.5/97.5 percentile bootstrap interval of the median of ``values``."""
    if not values:
        return []
    rng = random.Random(load_harness().SEED)  # noqa: S311 - Deterministic bootstrap sampling is not cryptographic.
    medians = sorted(
        statistics.median(rng.choices(values, k=len(values))) for _ in range(samples)
    )
    return [
        medians[int(samples * 0.025)],
        medians[min(int(samples * 0.975), samples - 1)],
    ]


def _pass_ratios(rows_a: Sequence[dict], rows_b: Sequence[dict]) -> list[float]:
    return [
        b["pass_ms"] / a["index_ms"]
        for a, b in zip(rows_a, rows_b, strict=True)
        if a["index_ms"] > 0 and b["pass_ms"] is not None
    ]


def _median(rows: Sequence[dict], key: str) -> float:
    return statistics.median(row[key] for row in rows)


def summarize(rows_a: Sequence[dict], rows_b: Sequence[dict]) -> dict:
    """Paired difference, bootstrap intervals and medians for one scenario."""
    index_module = load_index_scenarios()
    differences = [
        b["work_ms"] - a["work_ms"] for a, b in zip(rows_a, rows_b, strict=True)
    ]
    ratios = _pass_ratios(rows_a, rows_b)
    return {
        "a": list(rows_a),
        "b": list(rows_b),
        "difference_ms": differences,
        "bootstrap_95": load_harness().paired_bootstrap(differences),
        "bootstrap_95_statistic": "mean of paired work_ms differences",
        "a_work_ms_median": _median(rows_a, "work_ms"),
        "b_work_ms_median": _median(rows_b, "work_ms"),
        "difference_ms_median": statistics.median(differences),
        "a_index_ms_median": _median(rows_a, "index_ms"),
        "b_pass_ms_median": _median(rows_b, "pass_ms"),
        "ratio_median": statistics.median(ratios) if ratios else None,
        "ratio_bootstrap_95": paired_median_bootstrap(ratios),
        "ratio_bootstrap_95_statistic": "median of per-pair pass_ms/index_ms",
        "a_startup_ms_median": _median(rows_a, "startup_ms"),
        "b_startup_ms_median": _median(rows_b, "startup_ms"),
        "a_net_write_bytes_median": index_module.net_write_median(list(rows_a)),
        "b_net_write_bytes_median": index_module.net_write_median(list(rows_b)),
        "b_pass_summary_median": _pass_medians(rows_b),
    }


def run_target(
    target: Target, runs: int, measure: MeasureFn = measure_side, warmup: int = 0
) -> dict:
    """Interleave both sides for every scenario of one target."""
    scenarios = {}
    for scenario in SCENARIOS:
        for _ in range(warmup):
            for side in ("a", "b"):
                measure(scenario, side, target)
        paired: dict[int, dict[str, dict]] = {}
        for side, run in load_harness().interleaved_schedule(runs):
            paired.setdefault(run, {})[side] = measure(scenario, side, target)
        rows_a = [paired[run]["a"] for run in range(runs)]
        rows_b = [paired[run]["b"] for run in range(runs)]
        scenarios[scenario] = summarize(rows_a, rows_b)
    warnings = list(target.warnings)
    edit1 = scenarios["edit1_quality"]["b_pass_summary_median"].get(
        "measures_recomputed", 0
    )
    hub = scenarios["edit_hub_quality"]["b_pass_summary_median"].get(
        "measures_recomputed", 0
    )
    if hub <= edit1:
        warnings.append(f"hub_edit_recomputed={hub} <= edit1_recomputed={edit1}")
    return {
        "target": target.name,
        "kind": target.kind,
        "size_class": target.size_class,
        "file_count": target.file_count,
        "hub": target.hub,
        "leaf": target.leaf,
        "hub_closure_size": target.hub_closure_size,
        "leaf_closure_size": target.leaf_closure_size,
        "warnings": warnings,
        "scenarios": scenarios,
    }


def _ratios(scenarios: Mapping[str, dict]) -> dict:
    return {
        "cold_quality_k": scenarios["cold_quality"]["ratio_median"],
        "no_change_quality_j": scenarios["no_change_quality"]["ratio_median"],
        "edit1_quality_m": scenarios["edit1_quality"]["ratio_median"],
        "edit_hub_quality_m": scenarios["edit_hub_quality"]["ratio_median"],
    }


def _class_ratios(entries: Sequence[dict]) -> dict:
    ratios = {}
    for key in entries[0] if entries else {}:
        values = [entry[key] for entry in entries if entry[key] is not None]
        ratios[key] = statistics.median(values) if values else None
    return ratios


def proposed_ratios(results: Sequence[dict]) -> dict:
    """k, j and m proposals per target and per repository size class."""
    by_target = {row["target"]: _ratios(row["scenarios"]) for row in results}
    grouped: dict[str, list[dict]] = {}
    for row in results:
        grouped.setdefault(row["size_class"], []).append(_ratios(row["scenarios"]))
    return {
        "by_target": by_target,
        "by_size_class": {
            name: _class_ratios(entries) for name, entries in sorted(grouped.items())
        },
    }


def build_result(
    fixture: str,
    runs: int,
    repos: Sequence[Path],
    results: Sequence[dict],
    warmup: int,
) -> dict:
    return {
        "run_started_at": datetime.now(UTC).isoformat(),
        "machine_id": platform.node(),
        "load_average_1_5_15": list(os.getloadavg()),
        "fixture": fixture,
        "runs_per_scenario": runs,
        "warmup_pairs": warmup,
        "scenarios": list(SCENARIOS),
        "repos": [str(repo) for repo in repos],
        "targets": list(results),
        "proposed_ratios": proposed_ratios(results),
    }


def save_results(out: Path, data: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else ""
    )
    parser.add_argument("--fixture", choices=("tiny", "medium", "both"), default="tiny")
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        type=Path,
        help="local checkout to measure (repeatable); never fetched",
    )
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="discarded pairs per scenario before the retained runs",
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.runs < 1 or (not args.dry_run and args.runs < 30):
        parser.error(
            "measurement requires --runs >=30 (dry-run accepts smaller counts)"
        )
    if args.warmup < 0:
        parser.error("--warmup must be non-negative")
    if not args.dry_run and args.out is None:
        parser.error("--out is required for a measurement run")
    if args.dry_run:
        return args
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    repos = [path.resolve() for path in args.repo]
    for repo in repos:
        if not repo.is_dir():
            raise SystemExit(f"--repo is not a directory: {repo}")
    out = None
    if args.out is not None:
        try:
            out = output_path(args.out, [*repos, REPO_ROOT])
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
    schedule = load_harness().interleaved_schedule(1 if args.dry_run else args.runs)
    print("scenarios: " + " ".join(SCENARIOS))
    print("targets: " + " ".join([args.fixture, *_unique_names(repos)]))
    print("schedule: " + " ".join(f"{side.upper()}{run + 1}" for side, run in schedule))
    lock = lock_path()
    if args.dry_run:
        state = "held" if lock.is_dir() else "not held"
        print(f"lock: {state} {lock}")
        print("dry-run: PASS (measurements not run)")
        return 0
    if out is None:
        raise SystemExit("measurement output path is required")
    if not lock.is_dir():
        raise SystemExit(f"measurement lock is not held: {lock}")
    with tempfile.TemporaryDirectory(prefix="varde-quality-medium-") as medium:
        targets = resolve_targets(args.fixture, repos, Path(medium))
        targets = [select_edit_files(target) for target in targets]
        results = [
            run_target(target, args.runs, warmup=args.warmup) for target in targets
        ]
    data = build_result(args.fixture, args.runs, repos, results, args.warmup)
    save_results(out, data)
    for row in results:
        ratios = _ratios(row["scenarios"])
        print(
            f"{row['target']}: k={ratios['cold_quality_k']} "
            f"j={ratios['no_change_quality_j']} m={ratios['edit1_quality_m']} "
            f"m_hub={ratios['edit_hub_quality_m']}"
        )
    print(f"results: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
