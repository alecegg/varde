"""Load agreed code, school drafts and the Python corpus, run
``baseline_rank_buffer`` and print a report. Reads files and runs ``git`` on the
corpus cache; no model call.

    uv run python baseline_rank_run.py --run-state <dir>... \
        --raw-result index-buffer-result.json [--reference-repos <dir>...] \
        [--out result.json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import baseline_index_buffer as ib
import baseline_index_run as ir
import baseline_measure as bm
import baseline_rank_buffer as rb

REFERENCE_ROOT = Path.home() / "source/reference-repos"
DEFAULT_REFERENCE = (
    "acp-python-sdk",
    "cli-agent-orchestrator",
    "omnigent",
    "claude-agent-sdk-python",
)


def listed_paths(repo: Path) -> list[str]:
    """Tracked files of a git repo, else every file under the folder."""
    tracked = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "ls-files"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if tracked.returncode == 0 and tracked.stdout:
        return tracked.stdout.splitlines()
    return [str(p.relative_to(repo)) for p in repo.rglob("*.py")]


def reference_rows(repos: list[Path], per_repo: int) -> list[list[dict[str, Any]]]:
    """Per-file rows of sampled Python files of read-only reference repos."""
    files = []
    for repo in repos:
        taken = 0
        for path in ir.sample_paths(listed_paths(repo), per_repo * 3):
            blob = (repo / path).read_bytes() if (repo / path).is_file() else b""
            if ir.MIN_BYTES <= len(blob) <= ir.MAX_BYTES and taken < per_repo:
                taken += 1
                files.append(
                    bm.raw_measure_sources({"module.py": blob}, "python")["functions"]
                )
    return files


def fmt(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def tier_text(tier: float | str | None) -> str:
    if tier is None:
        return "-"
    return (
        tier
        if isinstance(tier, str)
        else f"{int(tier * 100)}%"
        if tier < 1
        else f"{int(tier)}pt"
    )


def band_text(
    band: tuple[float | None, float | None] | list[float | None] | None,
) -> str:
    if not band:
        return "-"
    low, high = band
    return (
        f"{fmt(low, 2).rstrip('0').rstrip('.')}-{fmt(high, 2).rstrip('0').rstrip('.')}"
    )


HEADER = (
    "metric | mode | pooled P | per-problem P | lopo / boot / draft (pts) | "
    "tier A | tier B | raw band 10pt | raw band 5pt | raw tier A/B before"
)
NEEDED_HEADER = (
    "metric | mode | problem sd | corpus sd | problems for 10pt (observed/corpus) | "
    "problems for 5pt (observed/corpus) | corpus files"
)


def per_problem_text(per_problem: dict[str, float | None]) -> str:
    return " ".join(fmt(v) for _, v in sorted(per_problem.items()))


def line(metric: str, mode: str, c: dict[str, Any], before: dict[str, Any]) -> str:
    errors = f"{fmt(c['lopo'])} / {fmt(c['boot'])} / {fmt(c['draft'])}"
    was = f"{tier_text(before['tier_a'])}/{tier_text(before['tier_b'])}"
    return (
        f"{metric} | {mode} | {fmt(c['pooled'])} | "
        f"{per_problem_text(c['per_problem'])} | "
        f"{errors} | {tier_text(c['tier_a'])} | {tier_text(c['tier_b'])} | "
        f"{band_text(c['band']['10'])} | {band_text(c['band']['5'])} | {was}"
    )


def needed_line(metric: str, mode: str, c: dict[str, Any]) -> str:
    n10, n5 = c["problems_needed"]["10"], c["problems_needed"]["5"]
    return (
        f"{metric} | {mode} | {fmt(c['problem_sd'])} | {fmt(c['corpus_sd'])} | "
        f"{n10['observed_sd']}/{n10['corpus_sd']} | "
        f"{n5['observed_sd']}/{n5['corpus_sd']} | "
        f"{c['corpus_files']}"
    )


def shift_lines(result: dict[str, Any], combined: dict[str, Any]) -> list[str]:
    lines = ["metric | mode | pooled P verified | pooled P verified+reference | shift"]
    for metric, entry in result.items():
        for mode, c in entry["cells"].items():
            other = combined[metric][mode]
            if c["pooled"] is not None and other is not None:
                shift = fmt(other - c["pooled"])
                lines.append(
                    f"{metric} | {mode} | {fmt(c['pooled'])} | {fmt(other)} | {shift}"
                )
    return lines


def report(
    result: dict[str, Any],
    raw: dict[str, dict[str, Any]],
    combined: dict[str, Any],
    sizes: dict[str, int],
) -> str:
    lines = [
        f"corpus sizes: {json.dumps(sizes, sort_keys=True)}",
        "",
        "best mode per metric (lowest tier A error)",
        HEADER,
    ]
    lines += [
        line(m, e["best_a"], e["cells"][e["best_a"]], raw[m]) for m, e in result.items()
    ]
    lines += ["", "best mode per metric (lowest tier B error)", HEADER]
    lines += [
        line(m, e["best_b"], e["cells"][e["best_b"]], raw[m]) for m, e in result.items()
    ]
    lines += ["", "problems needed (best tier A mode)", NEEDED_HEADER]
    lines += [
        needed_line(m, e["best_a"], e["cells"][e["best_a"]]) for m, e in result.items()
    ]
    lines += ["", "all modes", HEADER]
    lines += [
        line(m, mode, c, raw[m])
        for m, e in result.items()
        for mode, c in e["cells"].items()
    ]
    lines += ["", "problems needed (all modes)", NEEDED_HEADER]
    lines += [
        needed_line(m, mode, c)
        for m, e in result.items()
        for mode, c in e["cells"].items()
    ]
    lines += ["", "corpus robustness", *shift_lines(result, combined)]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-state", type=Path, nargs="+", required=True)
    parser.add_argument("--raw-result", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=ir.DEFAULT_CACHE)
    parser.add_argument("--per-repo", type=int, default=40)
    parser.add_argument("--reference-repos", type=Path, nargs="*")
    parser.add_argument("--seed", type=int, default=ib.DEFAULT_SEED)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    repos = args.reference_repos
    if repos is None:
        repos = [REFERENCE_ROOT / name for name in DEFAULT_REFERENCE]
    agreed = ir.load_agreed()
    drafts = ir.load_drafts(args.run_state)
    verified = [
        f for files in ir.corpus_rows(args.cache, args.per_repo).values() for f in files
    ]
    extra = reference_rows([r for r in repos if r.is_dir()], args.per_repo)
    result = rb.evaluate(agreed, drafts, verified, seed=args.seed)
    combined = rb.pooled_scores(agreed, verified + extra)
    raw = rb.raw_tiers(json.loads(args.raw_result.read_text())["evaluation"])
    sizes = {"verified_files": len(verified), "reference_files": len(extra)}
    if args.out:
        payload = {
            "evaluation": result,
            "combined_pooled": combined,
            "raw": raw,
            "sizes": sizes,
        }
        args.out.write_text(json.dumps(payload, sort_keys=True, indent=1))
    print(report(result, raw, combined, sizes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
