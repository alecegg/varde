"""Directional per-function exceedance discrimination (no model call).

    uv run python directional_run.py --run-state <dir>... \
        [--out-json result.json] [--out-txt report.txt]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import baseline_index_run as ir
import directional as dr
import discrimination_run as drun
from discrimination_run import fmt, pct


def load_sets(args: argparse.Namespace) -> dict[str, Any]:
    files = drun.load_reference(args)
    proxies = drun.pick_proxies(files, args.proxies)
    sources = {
        p.parent.parent.name: p.read_text()
        for p in sorted(ir.AGREED_ROOT.glob("*/python/solution.py"))
    }
    agreed = {p: ir.rows_of_source(s) for p, s in sources.items()}
    worse = {
        kind: {p: ir.rows_of_source(s) for p, s in by_problem.items()}
        for kind, by_problem in drun.degraded_sources(sources).items()
    }
    good = {f"agreed:{p}": rows for p, rows in agreed.items()}
    good |= {f"proxy:{drun.digest(rows)[:8]}": rows for rows in proxies}
    contested = drun.monolithic_drafts(ir.load_drafts(args.run_state))
    return {
        "good": good,
        "worse": worse,
        "contested": contested,
        "agreed": list(agreed),
    }


def analyse_set(
    good: Mapping[str, Any], worse: Mapping, contested: Mapping
) -> dict[str, Any]:
    fits = dr.fit_all(good, worse)
    best = {s: dr.best_form(f) for s, f in fits.items()}
    grid = dr.matrix(best)
    for result in best.values():
        if result is not None:
            result["percentile"] = dr.pool_percentile(
                good, result["signal"], result["threshold"]
            )
    return {
        "fits": fits,
        "best": best,
        "matrix": grid,
        "uncaught": dr.uncaught(grid),
        "contested": {
            s: dr.contested_view(good, contested, r)
            for s, r in best.items()
            if r is not None
        },
    }


def analyse_all(sets: Mapping[str, Any]) -> dict[str, Any]:
    good, worse, contested = sets["good"], sets["worse"], sets["contested"]
    agreed_only = {k: v for k, v in good.items() if k.startswith("agreed:")}
    curated = dr.curated_good(good)
    return {
        "sizes": {
            "good": len(good),
            "agreed": len(agreed_only),
            "curated": len(curated),
            "worse": sum(len(v) for v in worse.values()),
            "contested": len(contested),
        },
        "all": analyse_set(good, worse, contested),
        "curated": analyse_set(curated, worse, contested),
        "curated_ids": sorted(curated),
        "agreed_only": analyse_set(agreed_only, worse, contested),
        "lopo_agreed": dr.lopo(good, worse, sets["agreed"], keep_proxies=False),
        "lopo_agreed_plus_proxies": dr.lopo(
            good, worse, sets["agreed"], keep_proxies=True
        ),
    }


def types_at(result: Mapping[str, Any]) -> str:
    return (
        ",".join(k for k in result["by_type"] if dr.is_caught(result["by_type"], k))
        or "-"
    )


def signal_lines(block: Mapping[str, Any]) -> list[str]:
    lines = [
        (
            "signal | form | T raw | T pct | exceedance band | AUC | sens@90 | "
            "caught types | contested flagged"
        )
    ]
    for signal, r in block["best"].items():
        if r is None:
            lines.append(f"{signal} | no-data")
            continue
        threshold = "-" if r["threshold"] is None else fmt(r["threshold"], 1)
        percentile = "-" if r["percentile"] is None else pct(r["percentile"])
        band = (
            f"0..{pct(r['cut'])}"
            if r["form"] == "share"
            else f"max<={fmt(r['cut'], 1)}"
        )
        lines.append(
            f"{signal} | {r['form']} | {threshold} | {percentile} | {band} | "
            f"{fmt(r['auc'])} | {pct(r['sens'])} | {types_at(r)} | "
            f"{pct(block['contested'][signal]['flagged'])}"
        )
    return lines


def form_lines(block: Mapping[str, Any]) -> list[str]:
    lines = ["signal | form | T | cut | AUC | sens@90"]
    for signal, by_form in block["fits"].items():
        for form, r in by_form.items():
            if r is None:
                continue
            threshold = "-" if r["threshold"] is None else fmt(r["threshold"], 1)
            lines.append(
                f"{signal} | {form} | {threshold} | {fmt(r['cut'], 3)} | "
                f"{fmt(r['auc'])} | {pct(r['sens'])}"
            )
    return lines


def matrix_lines(block: Mapping[str, Any]) -> list[str]:
    signals = list(dr.SIGNALS)
    lines = ["type | " + " | ".join(signals)]
    for kind, row in block["matrix"].items():
        marks = [
            pct(row.get(s)) + ("*" if s in dr.MATCHED.get(kind, ()) else "")
            for s in signals
        ]
        lines.append(f"{kind} | " + " | ".join(marks))
    return lines


def matched_lines(block: Mapping[str, Any]) -> list[str]:
    lines = ["type | matched signals (sens@90) | caught | best any signal"]
    for kind, row in block["matrix"].items():
        matched = ", ".join(f"{s} {pct(row.get(s))}" for s in dr.MATCHED.get(kind, ()))
        info = block["uncaught"][kind]
        name, value = info["any_best"]
        lines.append(
            f"{kind} | {matched} | {'yes' if info['caught'] else 'NO'} | "
            f"{name} {pct(value)}"
        )
    return lines


def sensitivity_lines(result: Mapping[str, Any]) -> list[str]:
    lines = [
        (
            "signal | (a) all proxies | (b) curated (upper bound, circular) | "
            "agreed only | (c) LOPO agreed | "
            "LOPO agreed+proxies (held-out agreed accepted)"
        )
    ]
    for signal in dr.SIGNALS:
        cells = []
        for key in ("all", "curated", "agreed_only"):
            r = result[key]["best"].get(signal)
            cells.append(pct(r["sens"]) if r else "-")
        for key in ("lopo_agreed", "lopo_agreed_plus_proxies"):
            r = result[key].get(signal)
            cells.append(
                f"{pct(r['sens'])} ({pct(r['held_out_accepted'])})" if r else "-"
            )
        lines.append(f"{signal} | " + " | ".join(cells))
    return lines


def report_text(result: Mapping[str, Any]) -> str:
    main = result["all"]
    lines = [
        (
            "Directional discrimination report "
            "(one-sided per-function exceedance, sens@90% specificity)"
        ),
        f"sizes: {json.dumps(result['sizes'], sort_keys=True)}",
        "",
        "(a) best form per signal, all 24 proxies + agreed as the good set",
        *signal_lines(main),
        "",
        "degradation type x signal sens@90 (* = matched signal)",
        *matrix_lines(main),
        "",
        "matched signals per type",
        *matched_lines(main),
        "",
        "sensitivity to the proxy set",
        *sensitivity_lines(result),
        "curated good ids: " + ", ".join(result["curated_ids"]),
        "",
        "contested school drafts: AUC against good, flagged share (at the (a) cut)",
        *[
            f"{s} | AUC {fmt(v['auc'])} | flagged {pct(v['flagged'])}"
            for s, v in main["contested"].items()
        ],
        "",
        "all forms and thresholds chosen (a)",
        *form_lines(main),
    ]
    return "\n".join(lines)


def to_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json(v) for v in value]
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-state", type=Path, nargs="+", required=True)
    parser.add_argument("--cache", type=Path, default=ir.DEFAULT_CACHE)
    parser.add_argument("--per-repo", type=int, default=40)
    parser.add_argument("--reference-repos", type=Path, nargs="*")
    parser.add_argument("--proxies", type=int, default=24)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-txt", type=Path)
    args = parser.parse_args(argv)
    result = analyse_all(load_sets(args))
    text = report_text(result)
    if args.out_json:
        args.out_json.write_text(json.dumps(to_json(result), sort_keys=True, indent=1))
    if args.out_txt:
        args.out_txt.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
