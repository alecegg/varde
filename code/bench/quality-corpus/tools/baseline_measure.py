"""Measure per-metric baselines of a code directory with the installed scorer.

The measurement keeps exact pools (value -> token weight), the fragment-size
pool and the debt and token totals, so measurements of several problems pool by
adding counts and the pooled metrics equal a joint measurement. Metrics are
derived from a pool: size quantiles, comfort quantiles, fragment rate and debt
density. No scorer change, no model call; JSON output is deterministic.

``score_source`` is the one in-process "source code -> facts -> 0-100 view"
path shared by the page and the bench.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
CODE_SRC = ROOT / "code/src"
if str(CODE_SRC) not in sys.path:
    sys.path.insert(0, str(CODE_SRC))

from varde_code.quality_pass.facts import extract_facts  # noqa: E402, RUF100
from varde_code.quality_score.breakdown import breakdown  # noqa: E402, RUF100
from varde_code.quality_score.calibration import Calibration, load_calibration  # noqa: E402, RUF100
from varde_code.quality_score.costs import function_is_unmeasured, unique_functions  # noqa: E402, RUF100
from varde_code.quality_score.raw_measure import raw_measure_sources  # noqa: E402, RUF100
from varde_code.quality_score.scoring import ScopeScore, explain, score_scope  # noqa: E402, RUF100
from varde_code.quality_score.user_view import user_view  # noqa: E402, RUF100

DEFAULT_CALIBRATION = CODE_SRC / "varde_code/quality_score/calibration/placeholder.toml"
SUFFIXES = {"python": ".py", "typescript": ".ts", "csharp": ".cs"}
SKIPPED_DIRS = {"node_modules", "bin", "obj", "__pycache__", ".git"}
TEST_FILE = re.compile(
    r"(^test_.*\.py$|_test\.py$|\.test\.ts$|\.spec\.ts$|\.d\.ts$|Tests?\.cs$)"
)
POOLS = ("size", "cognitive", "depth", "fan_out", "tree_size")
QUANTILES = {  # metric -> (pool, numerator, denominator); same as threshold derivation
    "Plo": ("size", 25, 100),
    "t_frag": ("size", 50, 100),
    "Phi": ("size", 70, 100),
    "c0": ("cognitive", 70, 100),
    "dp0": ("depth", 85, 100),
    "k0": ("fan_out", 85, 100),
    "t0": ("tree_size", 85, 100),
}

Pool = dict[int, int]  # value -> total token weight
Measurement = dict[str, Any]


# ---- pure statistics --------------------------------------------------------


def weighted_quantile(
    pool: Mapping[int, int], numerator: int, denominator: int
) -> int | None:
    """Smallest value whose cumulative weight reaches numerator/denominator."""
    weights = {int(value): weight for value, weight in pool.items()}
    total = sum(weights.values())
    if total <= 0:
        return None
    running = 0
    for value in sorted(weights):
        running += weights[value]
        if running * denominator >= numerator * total:
            return value
    return max(weights)


def add_to_pool(pool: Pool, value: int, weight: int) -> None:
    pool[value] = pool.get(value, 0) + weight


def merge_pools(pools: Iterable[Mapping[int, int]]) -> Pool:
    merged: Pool = {}
    for pool in pools:
        for value, weight in pool.items():
            add_to_pool(merged, int(value), weight)
    return merged


def fragment_count(sizes: Mapping[int, int], t_frag: int) -> int:
    return sum(count for size, count in sizes.items() if int(size) <= t_frag)


# ---- measuring records ------------------------------------------------------


def included_paths(scored: ScopeScore) -> set[str]:
    return {
        f.path
        for f in scored.files
        if not f.excluded and not f.not_applicable and f.tokens > 0
    }


def structure_measured(record: Mapping[str, Any], function: dict[str, Any]) -> bool:
    return record.get("structure_confidence") != "low" and not function_is_unmeasured(
        function, dict(record)
    )


def record_pools(record: Mapping[str, Any]) -> dict[str, Pool]:
    """Token-weighted per-function pools of one facts record."""
    pools: dict[str, Pool] = {name: {} for name in POOLS}
    for function in unique_functions(list(record.get("functions") or ())):
        tokens = function.get("tokens") or 0
        if tokens <= 0:
            continue
        if not function.get("exempt_role"):
            add_to_pool(pools["size"], tokens, tokens)
        add_to_pool(pools["cognitive"], function.get("cognitive") or 0, tokens)
        if not structure_measured(record, function):
            continue
        for name in ("depth", "fan_out", "tree_size"):
            if function.get(name) is not None:
                add_to_pool(pools[name], function[name], tokens)
    return pools


def fragment_candidates(record: Mapping[str, Any]) -> Pool:
    """Sizes (value) with counts of file-scope functions that could be fragments."""
    sizes: Pool = {}
    if record.get("structure_confidence") == "low":
        return sizes
    for function in unique_functions(list(record.get("functions") or ())):
        eligible = (
            function.get("fragment_scope") == "file"
            and not function.get("exempt_role")
            and not function_is_unmeasured(function, dict(record))
        )
        if eligible:
            add_to_pool(sizes, function.get("tokens") or 0, 1)
    return sizes


def measure_records(
    records: Sequence[Mapping[str, Any]], calibration: Calibration, language: str
) -> Measurement:
    """Exact pools and totals of the scored records of one language."""
    dict_records = [dict(r) for r in records]
    scored = score_scope(dict_records, calibration)
    kept = included_paths(scored)
    kept_records = [r for r in dict_records if r.get("path") in kept]
    pools = [record_pools(r) for r in kept_records]
    fragment_tokens = sum(
        r.get("tokens") or 0
        for r in kept_records
        if r.get("structure_confidence") != "low"
    )
    return {
        "calibration": calibration.id,
        "language": language,
        "files": len(kept_records),
        "tokens": scored.tokens,
        "debt": scored.debt,
        "pools": {name: merge_pools(p[name] for p in pools) for name in POOLS},
        "fragment_sizes": merge_pools(fragment_candidates(r) for r in kept_records),
        "fragment_tokens": fragment_tokens,
    }


def pool_measurements(measurements: Sequence[Measurement]) -> Measurement:
    """Add measurements of one language and calibration; equals a joint measurement."""
    if not measurements:
        raise ValueError("nothing to pool")
    identity = {(m["language"], m["calibration"]) for m in measurements}
    if len(identity) != 1:
        raise ValueError(
            f"cannot pool different languages or calibrations: {sorted(identity)}"
        )
    language, calibration = next(iter(identity))
    return {
        "calibration": calibration,
        "language": language,
        "files": sum(m["files"] for m in measurements),
        "tokens": sum(m["tokens"] for m in measurements),
        "debt": sum(m["debt"] for m in measurements),
        "pools": {
            name: merge_pools(m["pools"][name] for m in measurements) for name in POOLS
        },
        "fragment_sizes": merge_pools(m["fragment_sizes"] for m in measurements),
        "fragment_tokens": sum(m["fragment_tokens"] for m in measurements),
    }


def metrics_of(measurement: Measurement) -> dict[str, Any]:
    """Per-metric baselines with numerators and denominators from one measurement."""
    values: dict[str, Any] = {}
    for name, (pool, numerator, denominator) in QUANTILES.items():
        values[name] = weighted_quantile(
            measurement["pools"][pool], numerator, denominator
        )
    t_frag = values["t_frag"]
    fragments = fragment_count(measurement["fragment_sizes"], t_frag) if t_frag else 0
    values["fragment_rate"] = ratio(fragments, measurement["fragment_tokens"])
    values["debt_density"] = ratio(measurement["debt"], measurement["tokens"])
    return values


def ratio(numerator: int, denominator: int) -> dict[str, Any]:
    """Rate with exact counts; per_1k_micro = numerator * 10^9 // denominator."""
    per_1k = numerator * 1_000_000_000 // denominator if denominator > 0 else None
    return {"numerator": numerator, "denominator": denominator, "per_1k_micro": per_1k}


# ---- directories and source text -------------------------------------------


def language_files(directory: Path, language: str) -> list[Path]:
    suffix = SUFFIXES[language]
    return sorted(
        path
        for path in directory.rglob(f"*{suffix}")
        if path.is_file()
        and not TEST_FILE.search(path.name)
        and not SKIPPED_DIRS & set(path.relative_to(directory).parts)
    )


def facts_of_directory(directory: Path, language: str) -> list[dict[str, Any]]:
    return [
        extract_facts(
            path.read_bytes(), language, path.relative_to(directory).as_posix()
        )
        for path in language_files(directory, language)
    ]


def measure_directory(
    directory: Path, language: str, calibration: Calibration
) -> Measurement:
    if language not in SUFFIXES:
        raise ValueError(f"unsupported language {language!r}")
    return measure_records(
        facts_of_directory(directory, language), calibration, language
    )


def raw_measure_directory(directory: Path, language: str) -> dict[str, Any]:
    """Raw per-function measures of a directory (no score, no confidence gate)."""
    if language not in SUFFIXES:
        raise ValueError(f"unsupported language {language!r}")
    sources = {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in language_files(directory, language)
    }
    return {"directory": str(directory), **raw_measure_sources(sources, language)}


def report(measurement: Measurement) -> dict[str, Any]:
    return {**measurement, "metrics": metrics_of(measurement)}


def score_source(
    source: str,
    language: str,
    calibration: Calibration | None = None,
    path: str | None = None,
    tests_passed: bool | None = None,
) -> dict[str, Any]:
    """Source code -> facts -> whitelisted 0-100 user view (no raw metrics)."""
    if language not in SUFFIXES:
        raise ValueError(f"unsupported language {language!r}")
    calibration = calibration or load_calibration(DEFAULT_CALIBRATION)
    name = path or f"code{SUFFIXES[language]}"
    scored = score_scope([extract_facts(source, language, name)], calibration)
    payload = explain(scored)
    payload["calibration"] = calibration.output_label
    return user_view(payload, breakdown(scored, calibration), tests_passed)


# ---- command line -----------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="+")
    parser.add_argument("--language", required=True, choices=sorted(SUFFIXES))
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--pool", action="store_true", help="pool the directories")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="raw per-function measures and min/median/max per directory",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.raw:
        raw = [raw_measure_directory(d, args.language) for d in args.directory]
        print(json.dumps(raw, sort_keys=True, indent=2))
        return 0
    calibration = load_calibration(args.calibration)
    measurements = [
        measure_directory(d, args.language, calibration) for d in args.directory
    ]
    if args.pool:
        out: Any = report(pool_measurements(measurements))
    else:
        out = [report(m) for m in measurements]
    print(json.dumps(out, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
