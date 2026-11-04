"""Strictness by discrimination: load agreed Python solutions, corpus proxy
modules, mechanical degradations and monolithic school drafts, then report per
metric the band that accepts known-good code and flags known-worse code. No
model call; deterministic.

    uv run python discrimination_run.py --run-state <dir>... \
        [--reference-repos <dir>...] [--proxies 24] \
        [--out-json result.json] [--out-txt report.txt]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import baseline_index_buffer as ib
import baseline_index_run as ir
import baseline_rank_buffer as rb
import baseline_rank_run as rr
import discrimination as dc
import quality_degrade as qd

FORMS = ("fn", "wp50", "wp75", "wp90", "wmean")
MONOLITHIC_PROBLEMS = ("job-scheduler", "report-pipeline")
MIN_PROXY_FUNCTIONS, MAX_PROXY_FUNCTIONS, MIN_PROXY_TOKENS = 3, 25, 150
CAUGHT_CELL = 0.5  # a type counts as caught by a metric from this fraction

Rows = ib.Rows


def digest(rows: Rows) -> str:
    blob = json.dumps(list(rows), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def pick_proxies(files: Sequence[Rows], count: int) -> list[Rows]:
    """Deterministic example-sized modules: the smallest content hashes."""
    fits = [
        rows
        for rows in files
        if MIN_PROXY_FUNCTIONS <= len(rows) <= MAX_PROXY_FUNCTIONS
        and sum(r["tokens"] for r in rows) >= MIN_PROXY_TOKENS
    ]
    return sorted(fits, key=digest)[:count]


def split_reference(files: Sequence[Rows], proxies: Sequence[Rows]) -> list[Rows]:
    chosen = {digest(rows) for rows in proxies}
    return [rows for rows in files if digest(rows) not in chosen]


def monolithic_drafts(drafts: ib.Drafts) -> dict[str, Rows]:
    """Single-function school drafts of the decomposition-sensitive problems."""
    return {
        f"{problem}/{run}/{school}": rows
        for problem, by_draft in drafts.items()
        if problem in MONOLITHIC_PROBLEMS
        for (run, school), rows in by_draft.items()
        if len(rows) == 1
    }


def degraded_sources(agreed_sources: Mapping[str, str]) -> dict[str, dict[str, str]]:
    """kind -> problem -> source, dropping no-ops (same as the unparsed input)."""
    out: dict[str, dict[str, str]] = {}
    for kind, degrade in qd.DEGRADATIONS.items():
        for problem, source in agreed_sources.items():
            result = degrade(source)
            if result != qd.identity(source):
                out.setdefault(kind, {})[problem] = result
    return out


class Scorers:
    """Value of every statistic form of a set of rows, per metric."""

    def __init__(self, reference: Sequence[Rows]) -> None:
        pooled = ib.pooled_files(reference)
        self.pairs = {m: ib.weighted_pairs(pooled, m) for m in ib.METRICS}
        self.fn = {m: rb.fn_scorer(m, rb.build_cdf(self.pairs[m])) for m in ib.METRICS}

    def value(self, rows: Rows, metric: str, form: str) -> float | None:
        if form == "fn":
            return self.fn[metric](rows)
        return ib.STATISTICS[form](rows, metric)


def values_of_items(
    scorers: Scorers, items: Mapping[str, Rows], metric: str, form: str
) -> dict[str, float]:
    found = {k: scorers.value(rows, metric, form) for k, rows in items.items()}
    return {k: v for k, v in found.items() if v is not None}


def band_view(scorers: Scorers, metric: str, form: str, cell: dict[str, Any]) -> dict:
    base, half = cell["baseline"], cell["half"]
    if form == "fn":
        low, high = rb.band_of_pairs(scorers.pairs[metric], base, half)
        view = {"unit": "percentile points", "points": half, "raw": [low, high]}
    else:
        view = {
            "unit": "raw",
            "points": None,
            "raw": [base - half, base + half],
            "relative": half / abs(base) if base else None,
        }
    return view


def analyse_metric(
    scorers: Scorers,
    metric: str,
    good: Mapping[str, Rows],
    worse: Mapping[str, Mapping[str, Rows]],
    contested: Mapping[str, Rows],
) -> dict[str, Any]:
    agreed = [k for k in good if k.startswith("agreed:")]
    cells: dict[str, Any] = {}
    for form in FORMS:
        values = values_of_items(scorers, good, metric, form)
        baseline = scorers.value(ib.pooled(good), metric, form)
        if baseline is None or len(values) < len(good):
            continue
        cell = dc.analyse(
            baseline,
            values,
            {
                kind: values_of_items(scorers, items, metric, form)
                for kind, items in worse.items()
            },
            values_of_items(scorers, contested, metric, form),
            agreed,
        )
        cell["band"] = band_view(scorers, metric, form, cell)
        cells[form] = cell
    best = dc.pick_recommended(cells)
    top = cells[best] if best else {"auc": None, "caught": None}
    return {
        "cells": cells,
        "recommended": best,
        "verdict": dc.verdict(top["auc"], top["caught"]),
    }


def control_shift(scorers: Scorers, agreed: Mapping[str, Rows], again: Mapping) -> dict:
    """Largest fn-percentile change caused by unparsing alone (per metric)."""
    return {
        m: max(
            abs(scorers.value(agreed[p], m, "fn") - scorers.value(again[p], m, "fn"))
            for p in agreed
        )
        for m in ib.METRICS
    }


def fmt(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def pct(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.0f}%"


def band_text(metric_result: dict[str, Any]) -> str:
    stat = metric_result["recommended"]
    if stat is None:
        return "-"
    cell = metric_result["cells"][stat]
    low, high = cell["band"]["raw"]
    if stat == "fn":
        return f"+-{fmt(cell['half'], 1)}pt (raw {fmt(low)}..{fmt(high)})"
    rel = cell["band"]["relative"]
    return f"+-{fmt(cell['half'])} ({pct(rel)}; raw {fmt(low)}..{fmt(high)})"


def types_text(cell: dict[str, Any], wanted_high: bool) -> str:
    names = [
        k
        for k, v in cell["by_type"].items()
        if v is not None and (v >= CAUGHT_CELL) == wanted_high
    ]
    return ",".join(names) or "-"


def metric_lines(result: Mapping[str, Any]) -> list[str]:
    lines = [
        (
            "metric | verdict | statistic | baseline | band | AUC | sens@90spec | "
            "agreed-only sens | contested caught | caught types | missed types"
        )
    ]
    for metric, entry in result.items():
        stat = entry["recommended"]
        if stat is None:
            lines.append(f"{metric} | no-data")
            continue
        c = entry["cells"][stat]
        lines.append(
            f"{metric} | {entry['verdict']} | {stat} | {fmt(c['baseline'])} | "
            f"{band_text(entry)} | {fmt(c['auc'])} | {pct(c['caught'])} | "
            f"{pct(c['agreed_only_caught'])} | {pct(c['contested_caught'])} | "
            f"{types_text(c, True)} | {types_text(c, False)}"
        )
    return lines


def paired_text(cell: dict[str, Any]) -> str:
    return " ".join(f"{k[:5]}={pct(v)}" for k, v in cell["paired_up"].items())


def all_statistic_lines(result: Mapping[str, Any]) -> list[str]:
    lines = [
        (
            "metric | stat | baseline | half | AUC | sens@90 | direction(worse-base) | "
            "upper AUC | upper sens@90 | paired-up by type"
        )
    ]
    for metric, entry in result.items():
        lines += [
            f"{metric} | {s} | {fmt(c['baseline'])} | {fmt(c['half'])} | "
            f"{fmt(c['auc'])} | {pct(c['caught'])} | {fmt(c['direction'])} | "
            f"{fmt(c['upper_auc'])} | {pct(c['upper_caught'])} | {paired_text(c)}"
            for s, c in entry["cells"].items()
        ]
    return lines


def matrix_lines(matrix: Mapping[str, Mapping[str, float | None]]) -> list[str]:
    metrics = list(ib.METRICS)
    lines = ["type | " + " | ".join(metrics)]
    lines += [
        f"{kind} | " + " | ".join(pct(by_metric.get(m)) for m in metrics)
        for kind, by_metric in matrix.items()
    ]
    return lines


def report_text(payload: Mapping[str, Any]) -> str:
    sizes = payload["sizes"]
    cost = payload["cost"]
    lines = [
        "Discrimination report (strictness set by discrimination, not reproducibility)",
        f"sizes: {json.dumps(sizes, sort_keys=True)}",
        f"cost: {json.dumps(cost, sort_keys=True)}",
        "",
        "recommended statistic per metric (band accepts >=90% of known-good)",
        *metric_lines(payload["metrics"]),
        "",
        "degradation type x metric: fraction caught at the recommended statistic",
        *matrix_lines(payload["matrix"]),
        "",
        "non-discriminating: " + (", ".join(payload["non_discriminating"]) or "none"),
        "no-op degradations dropped: " + json.dumps(payload["noops"], sort_keys=True),
        f"unparse control (max fn shift, points): {json.dumps(payload['control'])}",
        "",
        "all statistics",
        *all_statistic_lines(payload["metrics"]),
    ]
    return "\n".join(lines)


def load_reference(args: argparse.Namespace) -> list[Rows]:
    repos = args.reference_repos
    if repos is None:
        repos = [rr.REFERENCE_ROOT / name for name in rr.DEFAULT_REFERENCE]
    verified = [
        f for files in ir.corpus_rows(args.cache, args.per_repo).values() for f in files
    ]
    return verified + rr.reference_rows([r for r in repos if r.is_dir()], args.per_repo)


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

    started = time.perf_counter()
    files = load_reference(args)
    load_seconds = time.perf_counter() - started
    proxies = pick_proxies(files, args.proxies)
    scorers = Scorers(split_reference(files, proxies))

    sources = {
        path.parent.parent.name: path.read_text()
        for path in sorted(ir.AGREED_ROOT.glob("*/python/solution.py"))
    }
    started = time.perf_counter()
    agreed = {p: ir.rows_of_source(s) for p, s in sources.items()}
    again = {p: ir.rows_of_source(qd.identity(s)) for p, s in sources.items()}
    degraded = degraded_sources(sources)
    worse = {
        kind: {p: ir.rows_of_source(s) for p, s in by_problem.items()}
        for kind, by_problem in degraded.items()
    }
    degrade_seconds = time.perf_counter() - started
    contested = monolithic_drafts(ir.load_drafts(args.run_state))

    good = {f"agreed:{p}": rows for p, rows in agreed.items()}
    good |= {f"proxy:{digest(rows)[:8]}": rows for rows in proxies}
    metrics = {
        m: analyse_metric(scorers, m, good, worse, contested) for m in ib.METRICS
    }
    recommended = {m: e["recommended"] for m, e in metrics.items()}
    functions = sum(len(r) for r in files)
    variant_functions = sum(len(r) for k in worse.values() for r in k.values())
    payload = {
        "sizes": {
            "reference_files": len(files),
            "proxy_modules": len(proxies),
            "agreed": len(agreed),
            "worse_items": sum(len(v) for v in worse.values()),
            "contested_drafts": len(contested),
        },
        "cost": {
            "reference_functions": functions,
            "reference_seconds": round(load_seconds, 2),
            "ms_per_function": round(1000 * load_seconds / max(functions, 1), 2),
            "variant_functions": variant_functions,
            "variant_seconds_incl_degrading": round(degrade_seconds, 2),
        },
        "noops": {
            kind: [p for p in sources if p not in by_problem]
            for kind, by_problem in degraded.items()
            if len(by_problem) < len(sources)
        },
        "control": {
            m: round(v, 2) for m, v in control_shift(scorers, agreed, again).items()
        },
        "metrics": metrics,
        "matrix": dc.catch_matrix(
            {m: e["cells"] for m, e in metrics.items()}, recommended
        ),
        "non_discriminating": [
            m for m, e in metrics.items() if e["verdict"] != "discriminating"
        ],
        "proxy_ids": sorted(k for k in good if k.startswith("proxy:")),
        "contested_items": sorted(contested),
    }
    text = report_text(payload)
    if args.out_json:
        args.out_json.write_text(json.dumps(payload, sort_keys=True, indent=1))
    if args.out_txt:
        args.out_txt.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
