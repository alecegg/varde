# ruff: noqa: E501, S603, S607  (report text templates, git subprocess)
"""Score mined real refactor pairs before and after (no model call).

    uv run python mined_pairs_run.py collect --rows rows.json [--limit N]
    uv run python mined_pairs_run.py report --rows rows.json --out-json r.json --out-txt r.txt

``collect`` reads each changed .py file at the parent and child commit from the
pinned clones under the bench cache and scores both with each scorer via the
``score_scope`` pipeline that ``varde score`` uses (unrounded). ``report``
aggregates the saved rows.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import baseline_measure as bm
import mined_pairs as mp
import score_variants as sv
import scorer_candidates as sc
from varde_code.quality_score.breakdown import breakdown
from varde_code.quality_score.scoring import score_scope

PAIRS = Path(__file__).resolve().parent.parent / "pairs/mined/python"
CACHE = Path.home() / ".cache/varde/bench"
MAX_BYTES, MIN_BYTES = 200_000, 1
MICRO = 1_000_000
CUTS = {"placeholder": 73.6, "P+D2": 67.4}
SPECS = {
    "placeholder": sc.Spec("placeholder"),
    "p0=2": sc.Spec("p0=2", p0=2),
    "D2": sc.Spec("D2", dominance=2.0),
    "P+D2": sc.Spec("P+D2", p0=2, dominance=2.0),
}
BREAKDOWN_SPECS = ("placeholder", "P+D2")


def shipped_dominance(base: Any) -> Any:
    """Shipped form of P+D2: dominance strength 2.0 and Python p0=2."""
    strengths = {**base.global_strengths, "dominance": 2 * MICRO}
    return replace(sc.with_p0(base, 2), global_strengths=strengths)


def read_blob(clone: Path, sha: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(clone), "show", f"{sha}:{path}"],
        check=False,
        capture_output=True,
    )
    if result.returncode or not MIN_BYTES <= len(result.stdout) <= MAX_BYTES:
        return None
    return result.stdout.decode("utf-8", errors="replace")


def parses(source: str) -> bool:
    try:
        ast.parse(source)
    except SyntaxError, ValueError, RecursionError:
        return False
    return True


def function_debt_table(
    record: Mapping[str, Any], base: Any, spec: sc.Spec
) -> tuple[dict[str, int], dict[str, int], int]:
    """(debt incl. dominance, tokens) by function id, and file tokens."""
    gated = sv.gated_record(record, "gated")
    file = score_scope([gated], sc.with_p0(base, spec.p0)).files[0]
    low = bool(file.low_structure_confidence)
    debts = sc.function_debts(file.functions, base.global_strengths, spec, low)
    tokens = {f["id"]: f.get("tokens") or 0 for f in gated["functions"]}
    total = file.tokens
    scaled = {
        i: d
        + int(spec.dominance * max(0.0, 2 * tokens.get(i, 0) / max(1, total) - 1) * d)
        for i, d in debts.items()
    }
    return scaled, tokens, total


def score_side(source: str, names: set[str], base: Any) -> dict[str, Any]:
    record = sv.measured_record(source)
    out: dict[str, Any] = {
        "tokens": record["tokens"],
        "functions": len(record["functions"]),
    }
    for name, spec in SPECS.items():
        debts, tokens, _ = function_debt_table(record, base, spec)
        changed = mp.changed_density(debts, tokens, names)
        out[name] = {
            "file": sc.candidate_score(record, base, spec),
            "changed": None
            if changed is None
            else sc.density_score(changed[0], changed[1]),
            "worst3": mp.worst_ids(debts),
        }
    out["changed_functions"] = sum(
        mp.function_name(f["id"]) in names for f in record["functions"]
    )
    out["breakdown"] = {
        n: breakdown_rows(record, cal)
        for n, cal in (("placeholder", base), ("P+D2", shipped_dominance(base)))
    }
    return out


def breakdown_rows(record: Mapping[str, Any], cal: Any) -> dict[str, Any]:
    scored = bm.score_scope([dict(record)], cal)
    rows = breakdown(scored, cal, [dict(record)])
    return {
        r["name"]: {
            "lost": r["points_lost"] / MICRO,
            "targets": [t["id"] for t in r["fix_targets"] if t["line"] is not None][:3],
        }
        for r in rows
    }


def process_file(job: tuple[Mapping[str, Any], str]) -> dict[str, Any]:
    pair, path = job
    base = bm.load_calibration(bm.DEFAULT_CALIBRATION)
    clone = CACHE / pair["repo"].replace("/", "__")
    row = {"repo": pair["repo"], "sha": pair["child_sha"], "path": path}
    before = read_blob(clone, pair["parent_sha"], path)
    after = read_blob(clone, pair["child_sha"], path)
    if before is None or after is None:
        return {**row, "skip": "unreadable_or_size"}
    if not parses(before) or not parses(after):
        return {**row, "skip": "unparseable"}
    names = set(pair["changed_functions"])
    try:
        return {
            **row,
            "message": pair["intent_evidence"]["message"],
            "n_files": len(pair["changed_files"]),
            "names": sorted(names),
            "before": score_side(before, names, base),
            "after": score_side(after, names, base),
        }
    except Exception as error:  # noqa: BLE001 - a pair the scorer rejects is a skip
        return {**row, "skip": f"scorer_error:{type(error).__name__}"}


def load_pairs() -> list[dict[str, Any]]:
    pairs = []
    for file in sorted(PAIRS.glob("*.jsonl")):
        pairs.extend(json.loads(line) for line in file.read_text().splitlines() if line)
    return pairs


def collect(args: argparse.Namespace) -> None:
    pairs = load_pairs()
    jobs = [(p, f) for p in pairs for f in p["changed_files"]]
    jobs = jobs[: args.limit] if args.limit else jobs
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(process_file, jobs, chunksize=4))
    args.rows.write_text(json.dumps({"pairs": len(pairs), "rows": rows}))
    print(
        f"{len(pairs)} pairs, {len(jobs)} file jobs, {sum('skip' in r for r in rows)} skipped"
    )


# ---- report -----------------------------------------------------------------


def delta(row: Mapping[str, Any], scorer: str, level: str) -> float | None:
    b, a = row["before"][scorer][level], row["after"][scorer][level]
    return None if b is None or a is None else a - b


def deltas(rows: Sequence[Mapping[str, Any]], scorer: str, level: str) -> list[float]:
    return [d for r in rows if (d := delta(r, scorer, level)) is not None]


def group_stats(rows: Sequence[Mapping[str, Any]], level: str) -> dict[str, Any]:
    return {s: mp.paired_stats(deltas(rows, s, level)) for s in SPECS}


def grouped(rows: Sequence[Mapping[str, Any]], keys: Any) -> dict[str, list]:
    out: dict[str, list] = defaultdict(list)
    for r in rows:
        for k in keys(r):
            out[k].append(r)
    return dict(sorted(out.items()))


def cut_table(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    table = {}
    for scorer, cut in CUTS.items():
        b = [r["before"][scorer]["file"] for r in rows]
        a = [r["after"][scorer]["file"] for r in rows]
        table[scorer] = {
            "cut": cut,
            "before_below": mp.share_below(b, cut),
            "after_below": mp.share_below(a, cut),
            "accuracy": mp.cut_accuracy(b, a, cut),
            "mean_before": sum(b) / len(b),
            "mean_after": sum(a) / len(a),
        }
    return table


def category_table(rows: Sequence[Mapping[str, Any]], scorer: str) -> dict[str, Any]:
    names = sorted({n for r in rows for n in r["before"]["breakdown"][scorer]})
    out = {}
    for n in names:
        drops = []
        for r in rows:
            b = r["before"]["breakdown"][scorer].get(n, {"lost": 0.0})["lost"]
            a = r["after"]["breakdown"][scorer].get(n, {"lost": 0.0})["lost"]
            drops.append(b - a)
        out[n] = {
            "mean_before": sum(
                r["before"]["breakdown"][scorer].get(n, {"lost": 0.0})["lost"]
                for r in rows
            )
            / len(rows),
            "mean_drop": sum(drops) / len(drops),
            "share_shrunk": sum(d > 1e-9 for d in drops) / len(drops),
            "share_grew": sum(d < -1e-9 for d in drops) / len(drops),
        }
    return out


def top_category(side: Mapping[str, Any], scorer: str) -> str | None:
    rows = side["breakdown"][scorer]
    ranked = sorted(
        ((v["lost"], n) for n, v in rows.items() if v["targets"]), reverse=True
    )
    return ranked[0][1] if ranked and ranked[0][0] > 0 else None


def guidance_table(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for scorer in BREAKDOWN_SPECS:
        cat, own, chance = [], [], []
        for r in rows:
            names, side = set(r["names"]), r["before"]
            top = top_category(side, scorer)
            targets = side["breakdown"][scorer][top]["targets"] if top else []
            cat.append(mp.hit(targets, names))
            own.append(mp.hit(side[scorer]["worst3"], names))
            if side["changed_functions"]:
                chance.append(
                    mp.chance_hit(side["functions"], side["changed_functions"])
                )
        out[scorer] = {
            "top_category_targets_hit": mp.rate(cat),
            "top3_by_own_debt_hit": mp.rate(own),
            "n_with_targets": sum(h is not None for h in cat),
            "chance_top3": sum(chance) / len(chance) if chance else None,
            "n_with_changed_function_in_before": len(chance),
        }
    return out


def build_report(data: Mapping[str, Any]) -> dict[str, Any]:
    all_rows = data["rows"]
    skips = defaultdict(int)
    for r in all_rows:
        if "skip" in r:
            skips[r["skip"]] += 1
    rows = [r for r in all_rows if "skip" not in r]
    by = {
        "repo": grouped(rows, lambda r: [r["repo"]]),
        "intent": grouped(rows, lambda r: mp.intent_tags(r["message"]) or ["(other)"]),
        "size": grouped(rows, lambda r: [mp.size_bucket(r["before"]["tokens"])]),
        "files_per_commit": grouped(
            rows, lambda r: ["1 file" if r["n_files"] == 1 else ">1 files"]
        ),
    }
    report = {
        "pairs": data["pairs"],
        "file_jobs": len(all_rows),
        "scored": len(rows),
        "skips": dict(skips),
        "overall_file": group_stats(rows, "file"),
        "overall_changed": group_stats(rows, "changed"),
        "cuts": cut_table(rows),
        "categories": {s: category_table(rows, s) for s in BREAKDOWN_SPECS},
        "guidance": guidance_table(rows),
    }
    for name, groups in by.items():
        report[f"by_{name}"] = {
            g: {
                "n": len(rs),
                "file": group_stats(rs, "file"),
                "changed": group_stats(rs, "changed"),
            }
            for g, rs in groups.items()
        }
    return report


def pct(v: float | None) -> str:
    return "-" if v is None else f"{100 * v:.0f}%"


def stat_line(label: str, s: Mapping[str, Any]) -> str:
    if not s.get("n"):
        return f"{label}: n=0"
    return (
        f"{label}: n={s['n']} up {pct(s['up'])} tie {pct(s['tie'])} down {pct(s['down'])} "
        f"mean {s['mean']:+.2f} median {s['median']:+.2f} sign p={s['sign_p']:.3g}"
    )


def group_lines(title: str, groups: Mapping[str, Any], level: str) -> list[str]:
    lines = [f"{title} ({level} level): up% / mean delta"]
    for g, v in groups.items():
        cells = []
        for scorer, s in v[level].items():
            cells.append(
                f"{scorer} {pct(s.get('up'))}/{s['mean']:+.2f}"
                if s.get("n")
                else f"{scorer} -"
            )
        lines.append(f"  {g} (n={v['n']}): " + "; ".join(cells))
    return lines


def render(r: Mapping[str, Any]) -> str:
    lines = [
        f"Mined python refactor pairs: {r['pairs']} commits, {r['file_jobs']} changed files, {r['scored']} scored; skips {r['skips']}",
        "Paired delta = score(after) - score(before); up = after better.",
        "",
        "== Overall, file level ==",
        *[stat_line(s, v) for s, v in r["overall_file"].items()],
        "== Overall, changed-function level (only files with changed functions on both sides) ==",
        *[stat_line(s, v) for s, v in r["overall_changed"].items()],
        "",
        "== Cut lines (before=needs refactor, after=ok) ==",
        *[
            f"{s}: cut {c['cut']} before below {pct(c['before_below'])} after below {pct(c['after_below'])} accuracy {pct(c['accuracy'])} mean before {c['mean_before']:.1f} after {c['mean_after']:.1f}"
            for s, c in r["cuts"].items()
        ],
        "",
    ]
    for key in ("repo", "intent", "size", "files_per_commit"):
        for level in ("file", "changed"):
            lines += [*group_lines(f"By {key}", r[f"by_{key}"], level), ""]
    lines.append(
        "== Categories (points lost, mean over files; drop = before - after) =="
    )
    for scorer, table in r["categories"].items():
        lines.append(f"[{scorer}]")
        for n, c in sorted(table.items(), key=lambda kv: -kv[1]["mean_before"]):
            lines.append(
                f"  {n}: before {c['mean_before']:.2f} drop {c['mean_drop']:+.2f} shrunk {pct(c['share_shrunk'])} grew {pct(c['share_grew'])}"
            )
    lines += ["", "== Guidance hit rate (before file, changed-function names) =="]
    for scorer, g in r["guidance"].items():
        lines.append(
            f"{scorer}: top category's first 3 targets hit {pct(g['top_category_targets_hit'])} (n={g['n_with_targets']}); "
            f"top3 by own debt hit {pct(g['top3_by_own_debt_hit'])}; random-top3 chance {pct(g['chance_top3'])} (n={g['n_with_changed_function_in_before']})"
        )
    return "\n".join(lines) + "\n"


def report(args: argparse.Namespace) -> None:
    result = build_report(json.loads(args.rows.read_text()))
    if args.out_json:
        args.out_json.write_text(json.dumps(result, indent=1, sort_keys=True))
    text = render(result)
    if args.out_txt:
        args.out_txt.write_text(text)
    print(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--rows", type=Path, required=True)
    c.add_argument("--limit", type=int, default=0)
    c.add_argument("--workers", type=int, default=4)
    c.set_defaults(func=collect)
    r = sub.add_parser("report")
    r.add_argument("--rows", type=Path, required=True)
    r.add_argument("--out-json", type=Path)
    r.add_argument("--out-txt", type=Path)
    r.set_defaults(func=report)
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
