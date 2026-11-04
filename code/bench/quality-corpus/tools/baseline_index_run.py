"""Load agreed code, school first drafts and the verified Python corpus, then
run ``baseline_index_buffer`` and print a report. Reads files and runs ``git
show`` on the corpus cache; no model call.

    uv run python baseline_index_run.py --run-state <dir>... [--out result.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import baseline_index_buffer as ib
import baseline_measure as bm
import baseline_protocol as bp

HERE = Path(__file__).resolve().parent
AGREED_ROOT = HERE.parent / "baseline/agreed"
MANIFEST = HERE.parent / "corpus/verified/verified.json"
DEFAULT_CACHE = Path.home() / ".cache/varde/bench"
DRAFT_FILE = re.compile(r"^python__(?P<problem>.+)__write-(?P<school>.+)\.txt$")
SKIPPED_PARTS = {
    "test",
    "tests",
    "testing",
    "docs",
    "doc",
    "examples",
    "benchmarks",
    "vendor",
    "_vendor",
    "migrations",
    "scripts",
}
MIN_BYTES, MAX_BYTES = 500, 40_000


def rows_of_source(code: str, name: str = "solution.py") -> list[dict[str, Any]]:
    """Raw per-function rows of one source text treated as one module."""
    return bm.raw_measure_sources({name: code.encode()}, "python")["functions"]


def load_agreed(root: Path = AGREED_ROOT) -> dict[str, list[dict[str, Any]]]:
    return {
        path.parent.parent.name: rows_of_source(path.read_text())
        for path in sorted(root.glob("*/python/solution.py"))
    }


def load_drafts(run_states: list[Path]) -> ib.Drafts:
    """problem -> (run, school) -> rows, from each ``write-<school>.txt`` reply."""
    drafts: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = {}
    for run_dir in sorted(run_states):
        for path in sorted(run_dir.glob("python__*__write-*.txt")):
            match = DRAFT_FILE.match(path.name)
            code = bp.extract_code(path.read_text()) if match else None
            if match and code:
                key = (run_dir.name, match["school"])
                drafts.setdefault(match["problem"], {})[key] = rows_of_source(code)
    return drafts


def is_candidate(path: str) -> bool:
    parts = path.split("/")
    return (
        path.endswith(".py")
        and not SKIPPED_PARTS & set(parts[:-1])
        and not bm.TEST_FILE.search(parts[-1])
    )


def sample_paths(paths: list[str], count: int) -> list[str]:
    """Deterministic sample: the ``count`` candidates with the smallest path hash."""
    chosen = [p for p in paths if is_candidate(p)]
    return sorted(chosen, key=lambda p: hashlib.sha256(p.encode()).hexdigest())[:count]


def git_out(repo: Path, *args: str) -> bytes:
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
    ).stdout


def corpus_rows(cache: Path, per_repo: int) -> dict[str, list[list[dict[str, Any]]]]:
    """repo -> per-file rows for the sampled Python files of each verified repo."""
    manifest = json.loads(MANIFEST.read_text())
    result: dict[str, list[list[dict[str, Any]]]] = {}
    for repo in manifest["repositories"]:
        if repo["status"] != "verified" or "Python" not in repo["languages"]:
            continue
        checkout, sha = cache / repo["name"].replace("/", "__"), repo["pin_sha"]
        names = (
            git_out(checkout, "ls-tree", "-r", "--name-only", sha).decode().splitlines()
        )
        files = []
        for path in sample_paths(names, per_repo * 3):
            blob = git_out(checkout, "show", f"{sha}:{path}")
            if MIN_BYTES <= len(blob) <= MAX_BYTES and len(files) < per_repo:
                files.append(
                    bm.raw_measure_sources({"module.py": blob}, "python")["functions"]
                )
        result[repo["name"]] = files
    return result


def fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def tier_text(tier: float | str) -> str:
    return tier if isinstance(tier, str) else f"{int(tier * 100)}%"


BUFFER_HEADER = (
    "metric | variant | best stat | baseline | lopo / boot / spread | "
    "draft_vs_agreed | tier A | tier B | remedy | units for 10%"
)
CORPUS_HEADER = (
    "metric | stat | agreed | corpus median | percentile | "
    "file dispersion | units for 10%"
)
ALL_HEADER = (
    "metric | stat | baseline | lopo | boot | spread | tier A | tier B | degenerate"
)


def threshold_lines() -> list[str]:
    keys = ib.CALIBRATION_KEY
    mapped = [f"{m}={k} ({ib.COMFORT[m]:g})" for m, k in keys.items()]
    fixed = [f"{m} ({ib.COMFORT[m]:g})" for m in ib.FALLBACK_THRESHOLD]
    return [
        "comfort thresholds (placeholder.toml language.python): " + ", ".join(mapped),
        "no calibration key, earlier fixed choice kept: " + ", ".join(fixed),
    ]


def buffer_line(
    metric: str, entry: dict[str, Any], variant: str, position: dict[str, Any]
) -> str:
    best = entry["best_b" if variant == "B" else "best"]
    remedy = entry["remedy_b" if variant == "B" else "remedy"]
    c = entry["cells"][best]
    errors = f"{fmt(c['lopo'])} / {fmt(c['bootstrap'])} / {fmt(c['draft'])}"
    units = position[metric][best]["units_for_10pct"]
    return (
        f"{metric} | {variant} | {best} | {fmt(c['baseline'])} | {errors} | "
        f"{fmt(c['draft_vs_agreed'])} | {tier_text(c['tier'])} | "
        f"{tier_text(c['tier_b'])} | {json.dumps(remedy, sort_keys=True)} | {units}"
    )


def all_stat_line(metric: str, stat: str, c: dict[str, Any]) -> str:
    return (
        f"{metric} | {stat} | {fmt(c['baseline'])} | {fmt(c['lopo'])} | "
        f"{fmt(c['bootstrap'])} | {fmt(c['draft'])} | {tier_text(c['tier'])} | "
        f"{tier_text(c['tier_b'])} | {'yes' if c['degenerate'] else 'no'}"
    )


def reach_lines(result: dict[str, Any]) -> list[str]:
    lines = ["tier B ranking (non-degenerate statistics reaching the step):"]
    for step in map(str, ib.BUFFER_STEPS):
        lines.append(f"-- reaching {int(float(step) * 100)}%:")
        lines += [
            f"{m} | {', '.join(e['reach_b'][step]) or '-'}" for m, e in result.items()
        ]
    return lines


def corpus_line(metric: str, stat: str, p: dict[str, Any]) -> str:
    return (
        f"{metric} | {stat} | {fmt(p['agreed'])} | {fmt(p['corpus_median'])} | "
        f"{fmt(p['percentile'])} | {fmt(p['file_dispersion_median'])} | "
        f"{p['units_for_10pct']}"
    )


def report(result: dict[str, Any], position: dict[str, Any]) -> str:
    lines = [*threshold_lines(), "", BUFFER_HEADER]
    for variant in ("A", "B"):
        lines += [buffer_line(m, e, variant, position) for m, e in result.items()]
    lines += ["", *reach_lines(result), "", ALL_HEADER]
    lines += [
        all_stat_line(m, s, c) for m, e in result.items() for s, c in e["cells"].items()
    ]
    lines += ["", CORPUS_HEADER]
    lines += [
        corpus_line(m, s, p) for m, stats in position.items() for s, p in stats.items()
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-state", type=Path, nargs="+", required=True)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--per-repo", type=int, default=40)
    parser.add_argument("--seed", type=int, default=ib.DEFAULT_SEED)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    agreed = load_agreed()
    result = ib.evaluate(agreed, load_drafts(args.run_state), seed=args.seed)
    corpus = corpus_rows(args.cache, args.per_repo)
    position = ib.corpus_position(
        agreed, [f for files in corpus.values() for f in files]
    )
    if args.out:
        args.out.write_text(
            json.dumps(
                {"evaluation": result, "corpus_position": position},
                sort_keys=True,
                indent=1,
            )
        )
    print(report(result, position))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
