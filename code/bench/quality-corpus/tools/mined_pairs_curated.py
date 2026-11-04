# ruff: noqa: E501  (report text templates)
"""Curated subset of the mined python refactor pairs (no model call).

    uv run python mined_pairs_curated.py collect --rows rows.json [--min-tokens N] [--max-fn N] [--max-size-change F]
    uv run python mined_pairs_curated.py report --rows rows.json --out-json r.json --out-txt r.txt

Commit-level filters pick single-file commits whose message states a quality
refactor intent and none of the excluded intents. File-level filters (size,
size change) apply to the scored rows. Scoring and the report reuse
``mined_pairs_run``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import mined_pairs as mp
import mined_pairs_run as run

INCLUDE = re.compile(
    r"extract|flatten|early[ -]return|\bsplit|reduc\w* complexity|simplif|renam",
    re.IGNORECASE,
)
EXCLUDE = re.compile(
    r"\bfix|\bbug|\bfeature|\badd|support|deprecat|\bperf|speed", re.IGNORECASE
)
TOP = 3


def commit_ok(pair: Mapping[str, Any], max_functions: int, include: re.Pattern) -> bool:
    message = pair["intent_evidence"]["message"]
    return (
        len(pair["changed_files"]) == 1
        and 1 <= len(pair["changed_functions"]) <= max_functions
        and bool(include.search(message))
        and not EXCLUDE.search(message)
    )


def row_ok(row: Mapping[str, Any], min_tokens: int, max_change: float) -> bool:
    if "skip" in row:
        return False
    before, after = row["before"]["tokens"], row["after"]["tokens"]
    return before >= min_tokens and abs(after - before) <= max_change * before


def collect(args: argparse.Namespace) -> None:
    pairs = [p for p in run.load_pairs() if commit_ok(p, args.max_fn, INCLUDE)]
    jobs = [(p, p["changed_files"][0]) for p in pairs]
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(run.process_file, jobs, chunksize=4))
    args.rows.write_text(json.dumps({"pairs": len(pairs), "rows": rows}))
    print(f"{len(pairs)} commit-filtered pairs, {len(rows)} scored/skipped rows")


def hit_vs_chance(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Own-debt top-3 hit rate against per-pair random top-3 chance, same rows."""
    out: dict[str, Any] = {}
    usable = [r for r in rows if r["before"]["changed_functions"]]
    for scorer in run.BREAKDOWN_SPECS:
        own, cat, chance = [], [], []
        for r in usable:
            names, side = set(r["names"]), r["before"]
            own.append(mp.hit(side[scorer]["worst3"], names))
            top = run.top_category(side, scorer)
            targets = side["breakdown"][scorer][top]["targets"] if top else []
            cat.append(mp.hit(targets, names))
            chance.append(mp.chance_hit(side["functions"], side["changed_functions"]))
        known = [(o, c) for o, c in zip(own, chance, strict=True) if o is not None]
        out[scorer] = {
            "n": len(usable),
            "own_top3_hit": mp.rate(own),
            "top_category_hit": mp.rate(cat),
            "chance_top3_same_rows": sum(c for _, c in known) / len(known)
            if known
            else None,
            "n_own": len(known),
        }
    return out


def build(data: Mapping[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    kept = [r for r in data["rows"] if row_ok(r, args.min_tokens, args.max_size_change)]
    report = run.build_report({"pairs": data["pairs"], "rows": kept})
    report["hit_vs_chance"] = hit_vs_chance(kept)
    report["filters"] = {
        "max_functions": args.max_fn,
        "min_tokens": args.min_tokens,
        "max_size_change": args.max_size_change,
        "commit_pairs": data["pairs"],
        "rows_after_file_filters": len(kept),
    }
    return report


def render(report: Mapping[str, Any]) -> str:
    f = report["filters"]
    lines = [
        (
            f"CURATED mined python pairs: n={f['rows_after_file_filters']} files "
            f"(commit filters kept {f['commit_pairs']}; functions<= {f['max_functions']}, "
            f"tokens>= {f['min_tokens']}, |size change|<= {f['max_size_change']:.0%})"
        ),
        "",
        "== Overall, file level ==",
        *[run.stat_line(s, v) for s, v in report["overall_file"].items()],
        "== Overall, changed-function level ==",
        *[run.stat_line(s, v) for s, v in report["overall_changed"].items()],
        "",
        "== Cut lines (before=needs refactor, after=ok) ==",
        *[
            f"{s}: cut {c['cut']} before below {run.pct(c['before_below'])} after below {run.pct(c['after_below'])} accuracy {run.pct(c['accuracy'])}"
            for s, c in report["cuts"].items()
        ],
        "",
        "== Guidance hit rate vs per-pair random top-3 chance (same rows) ==",
    ]
    for scorer, g in report["hit_vs_chance"].items():
        lines.append(
            f"{scorer}: own top3 hit {run.pct(g['own_top3_hit'])} (n={g['n_own']}); top-category targets hit {run.pct(g['top_category_hit'])}; chance {run.pct(g['chance_top3_same_rows'])}"
        )
    return "\n".join(lines) + "\n"


def report(args: argparse.Namespace) -> None:
    result = build(json.loads(args.rows.read_text()), args)
    if args.out_json:
        args.out_json.write_text(json.dumps(result, indent=1, sort_keys=True))
    text = render(result)
    if args.out_txt:
        args.out_txt.write_text(text)
    print(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, func in (("collect", collect), ("report", report)):
        p = sub.add_parser(name)
        p.add_argument("--rows", type=Path, required=True)
        p.add_argument("--max-fn", type=int, default=5)
        p.add_argument("--min-tokens", type=int, default=1000)
        p.add_argument("--max-size-change", type=float, default=0.4)
        if name == "collect":
            p.add_argument("--workers", type=int, default=4)
        else:
            p.add_argument("--out-json", type=Path)
            p.add_argument("--out-txt", type=Path)
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
