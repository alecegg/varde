# ruff: noqa: E501  (report text templates)
"""Evaluate the shadow measure strengths (sn, sm, sd) on the dev split; no model calls.

    uv run python measures_eval_run.py --check

Each strength is tried at a small grid of values, one at a time, then all
together, against the shipped calibration with all three forced off. Scores use the product path
(exact facts, user-view score). Dev split only; the test split is refused.
A strength ships on only if ``measures_eval.problems`` is empty for it.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import baseline_q4q5 as q45
import delta_eval as de
import delta_eval_run as der
import measures_eval as me
import mutation_pairs as mp
import score_separation_run as ssr
from score_dataset import default_dataset
from varde_code.quality_score.calibration import Calibration, load_calibration
from varde_code.quality_score.delta import WORSE_TOLERANCE
from varde_code.quality_score.file_facts import exact_facts
from varde_code.quality_score.reference import CALIBRATION, score_of_facts

OUT_DEFAULT = (
    ssr.USER_HOME
    / "source/agent-memory/projects/varde-py/working/plans"
    / "2026-10-31-vqs-delta-and-measures/notes/measures-eval.md"
)
KINDS = (
    "rename_vague",
    "guard_nesting",
    "inline_helpers",
    "add_params",
    "compound",
    "deep_chain",
    "wrappers",
    "monolith",
)
_FACTS: dict[tuple[str, str, str], dict[str, Any]] = {}


def cached_facts(source: Any, language: str, path: str) -> dict[str, Any]:
    text = source if isinstance(source, str) else source.decode("utf-8-sig", "replace")
    key = (text, language, path)
    if key not in _FACTS:
        _FACTS[key] = exact_facts(text, language, path)
    return _FACTS[key]


def scorer_for(calibration: Calibration) -> Any:
    def score(source: str, path: str = "module.py") -> float | None:
        try:
            return score_of_facts(cached_facts(source, "python", path), calibration)
        except Exception:  # noqa: BLE001 - a source the extractor rejects is skipped
            return None

    return score


def rescored(
    repos: Mapping[str, list[der.RepoFile]], score: Any
) -> dict[str, list[der.RepoFile]]:
    out = {}
    for name, files in repos.items():
        scored = [(f, score(f.source, f.path)) for f in files]
        out[name] = [
            der.RepoFile(f.path, f.source, v) for f, v in scored if v is not None
        ]
    return out


def pair_view(scored: list[der.PairScore], repos: Mapping[str, Any]) -> dict[str, Any]:
    result = der.eval_pairs(scored, repos)
    drops = [de.worse_than_before(p.after, p.before, WORSE_TOLERANCE) for p in scored]
    higher = [p.after > p.before for p in scored]
    return {
        **result,
        "worse_tol": de.tally(drops),
        "after_higher": de.tally(higher),
    }


def run_config(calibration: Calibration, ctx: Mapping[str, Any]) -> dict[str, Any]:
    score = scorer_for(calibration)
    repos = rescored(ctx["repos"], score)
    per_repo = [
        der.eval_files(f, "full", ctx["variant_files"], score) for f in repos.values()
    ]
    full = der.merge_eval(per_repo)
    scored, _ = der.score_pairs(ctx["pair_sources"], score)
    dev_pairs = [p for p in scored if p.dev]
    pairs_all, pairs_dev = pair_view(scored, repos), pair_view(dev_pairs, repos)
    sources = ctx["label_sources"]
    scores = {k: score(s) for k, s in sources.items()}
    scores = {k: v for k, v in scores.items() if v is not None}
    view = ssr.set_view(scores, ctx["label_items"])
    return {
        "good_product": full["good_product"],
        "good_below": full["good_below"],
        "kinds": full["kinds"],
        "deltas": full["deltas"],
        "pairs_all": pairs_all,
        "pairs_dev": pairs_dev,
        "pair_fp": pairs_dev["worse_tol"],
        "monolith_below": full["kinds"]["monolith"]["below"],
        "label": view,
        "drafts_below": {"rate": view["sens_monolith"]},
        "agreed": {
            i.key: scores[i.key]
            for i in ctx["label_items"]
            if i.key.startswith("agreed:")
        },
        "file_scores": {
            f"{name}:{f.path}": f.score for name, files in repos.items() for f in files
        },
        "draft_mean": view["sets"]["contested"]["mean"],
        "wrapper_n": sum(1 for i in ctx["label_items"] if i.kind == "wrappers"),
        "q": q45.evaluate(calibration, ctx["dataset"]),
    }


# ---- report -----------------------------------------------------------------


def worse_cell(deltas: list[float]) -> dict[str, Any]:
    return de.tally([de.worse_than_before(d, 0.0, WORSE_TOLERANCE) for d in deltas])


def kind_row(name: str, result: Mapping[str, Any]) -> str:
    cells = []
    for kind in KINDS:
        below = result["kinds"].get(kind, {}).get("below")
        worse = worse_cell(result["deltas"].get(kind, []))
        cells.append(f"{de.fmt(worse)} / {de.fmt(below)}" if below else "-")
    return f"{name} | " + " | ".join(cells)


def kinds_table(results: list[tuple[str, Any, Mapping[str, Any]]]) -> list[str]:
    lines = [
        "config | " + " | ".join(KINDS),
        "--- | " + " | ".join("---" for _ in KINDS),
    ]
    return lines + [kind_row(name, r) for name, _, r in results]


def good_table(results: list[tuple[str, Any, Mapping[str, Any]]]) -> list[str]:
    lines = [
        "config | good files below p10 (ref n >= 20) | good files below p10 (all) | dev-hash refactor-after worse than before (tolerance) | all pairs worse (tolerance) | dev pairs: before below p10 -> after below p10 | dev pairs: improved among before-below | dev files losing more than 0.5 points vs off | dev pairs: after above before",
        "--- | --- | --- | --- | --- | --- | --- | --- | ---",
    ]
    for name, _, r in results:
        p = r["pairs_dev"]
        lines.append(
            f"{name} | {de.fmt(r['good_product'])} | {de.fmt(r['good_below'])} | {de.fmt(r['pair_fp'])} | {de.fmt(r['pairs_all']['worse_tol'])} | {de.fmt(p['before_below_p10'])} -> {de.fmt(p['after_below_p10'])} | {de.fmt(p['improved_among_before_below'])} | {de.fmt(r['file_loss'])} | {de.fmt(p['after_higher'])}"
        )
    return lines


def q_cell(part: Mapping[str, Any]) -> str:
    return (
        f"{100 * part['rate']:.1f}% ({part['hits']}/{part['n']}, n={part['n']})"
        if part["rate"] is not None
        else f"- (n={part['n']})"
    )


def q_table(results: list[tuple[str, Any, Mapping[str, Any]]]) -> list[str]:
    langs = list(results[0][2]["q"])
    head = [f"{lang} {part}" for lang in langs for part in ("Q4", "Q5")]
    lines = ["config | " + " | ".join(head), "--- | " + " | ".join("---" for _ in head)]
    for name, _, r in results:
        cells = [q_cell(r["q"][lang][part]) for lang in langs for part in ("q4", "q5")]
        lines.append(f"{name} | " + " | ".join(cells))
    return lines


def label_table(results: list[tuple[str, Any, Mapping[str, Any]]]) -> list[str]:
    agreed = sorted(results[0][2]["agreed"])
    head = [k.removeprefix("agreed:") for k in agreed]
    lines = [
        "config | "
        + " | ".join(head)
        + " | school drafts flagged (n) | monolith dev files below p10 | wrappers (labelled, flagged) | AUC good>worse | school draft mean score",
        "--- | " + " | ".join("---" for _ in head) + " | --- | --- | --- | --- | ---",
    ]
    for name, _, r in results:
        view = r["label"]
        n_draft = view["sets"]["contested"]["n"]
        wrappers = view["sens_by_kind"].get("wrappers")
        lines.append(
            f"{name} | "
            + " | ".join(f"{r['agreed'][k]:.1f}" for k in agreed)
            + f" | {_pct(view['sens_monolith'])} (n={n_draft}) | {de.fmt(r['monolith_below'])} | {_pct(wrappers)} (n={r['wrapper_n']} wrappers items) | {view['auc_good_worse']:.2f} (n={view['sets']['good']['n']} good, {view['sets']['worse']['n']} worse) | {r['draft_mean']:.1f}"
        )
    return lines


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.0f}%"


def decision_lines(
    results: list[tuple[str, Mapping[str, float], Mapping[str, Any]]],
) -> tuple[list[str], list[str]]:
    verdicts = me.decisions(results)
    lines, ships = [], []
    for name, problems in verdicts.items():
        if problems:
            lines.append(
                f"- {name}: stays off - "
                + "; ".join(p.split(": ", 1)[1] for p in problems)
            )
            continue
        ships.append(name)
        r = {n: res for n, _, res in results}[name]
        base_monolith = results[0][2]["monolith_below"]
        lines.append(
            f"- {name}: ships on (good-file false positive: pair worse-than-before {de.fmt(r['pair_fp'])}, below p10 {de.fmt(r['good_product'])}, dev files losing points {de.fmt(r['file_loss'])}; monolith dev files below p10 {de.fmt(base_monolith)} -> {de.fmt(r['monolith_below'])}, reported not blocking)"
        )
    return lines, ships


def render(
    results: list[tuple[str, Any, Any]], sizes: Mapping[str, int]
) -> tuple[list[str], list[str]]:
    decided, ships = decision_lines(results)
    base = results[0][2]
    lines = [
        "# Measures evaluation (strengths sn, sm, sd; deterministic, no model calls)",
        "",
        f"Dev split only (`splits.lock`; the test split is refused). Repo styles: {len(sizes)} ({', '.join(f'{k} n={v}' for k, v in sizes.items())}). Scores are product scores (shipped calibration with the three strengths set per row, user view, exact facts), each configuration re-scores the reference and all variants. The tolerance for 'worse than before' is {WORSE_TOLERANCE} points (delta.py).",
        "",
        "Grid: each strength alone at 0.5, 1.0, 2.0, then all three together at the same value. Target of sn: guard_nesting; sm: rename_vague; sd: wrappers. No other parameter changes.",
        "",
        "Budget for a strength to ship on: good-file false positives within 10 percent (measured on dev-hash refactor-after files worse than before, n=65) and below-p10 on good files within 0.12 (the bar from the t3 evaluation; it is 10% only in expectation); each turned-on strength lifts its target's leave-one-out below-p10 rate by at least 5 points; dev files losing more than the tolerance against strengths-off stay within 10 percent (the absolute good-file cost: below-p10 on good files is about 10% by construction); Q4 and Q5 pass rates and inversions, the 4 agreed samples (no loss over the tolerance), school-draft flags and the dev pairs where after scores above before (within 5 points) do not get worse. The monolith share is reported but does not block (a reference that moves down also moves the p10 line). Rules were fixed before the first run except the last two checks (files losing points, pairs after above before), added after it because below-p10 is relative by construction.",
        "",
        "## Decisions",
        "",
        *decided,
        "",
        f"Ships on: {', '.join(ships) if ships else 'none (all strengths stay off)'}",
        "",
        "## Degradations: worse than before at the tolerance (circular) / below reference p10 (leave-one-out), full dev reference",
        "",
        *kinds_table(results),
        "",
        "## Good files and mined pairs (dev-hash pairs, n="
        + str(base["pairs_dev"]["worse_tol"]["n"])
        + " of the 158 curated)",
        "",
        *good_table(results),
        "",
        "## Q4 and Q5 (dev split, exact facts)",
        "",
        *q_table(results),
        "",
        "## Agreed samples, school drafts, monolith, wrappers (labelled set of 66 items; guard only, not used to choose)",
        "",
        *label_table(results),
        "",
        "## Caveats",
        "",
        "- The mined-pair `strictly closer` measure of the region simulation does not read the scorer, so it cannot move with a strength; the score-based analogue is the 'improved among before-below' column.",
        "- Worse-than-before rates compare a degradation with its own original and are partly circular; the leave-one-out below-p10 rate is the independent one.",
        "- Degradation and good-file rates have n of 11 to 97 per cell, so differences of a few points are within noise.",
    ]
    return lines, ships


def build_parser() -> argparse.ArgumentParser:
    parser = der.build_parser()
    parser.description = __doc__
    parser.set_defaults(out=OUT_DEFAULT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        me.require_dev_split(args.split)
    except me.SplitError as err:
        print(f"refusing: {err}", file=sys.stderr)
        return 2
    # the labelled set keeps score_separation_run's sample size and reference repos
    label_args = argparse.Namespace(
        **{**vars(args), "per_repo": 40, "reference_repos": None}
    )
    ctx, sizes = load_context(args, label_args)
    base = load_calibration(CALIBRATION)
    mp.extract_facts = cached_facts
    q45.extract_facts = mp.extract_facts
    results = []
    for name, values in me.config_names():
        results.append((name, values, run_config(me.with_strengths(base, values), ctx)))
        print(f"done {name}", file=sys.stderr, flush=True)
    off_scores = results[0][2]["file_scores"]
    for _, _, result in results:
        result["file_loss"] = me.file_loss(off_scores, result["file_scores"])
    lines, ships = render(results, sizes)
    out = der.plan_out(args.out)
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    if not args.check:
        return 0
    problems = [*de.missing_n(lines), *ships_problems(results, ships)]
    print("check: " + ("ok" if not problems else f"FAIL {problems}"))
    return 0 if not problems else 1


def load_context(
    args: argparse.Namespace, label_args: argparse.Namespace
) -> tuple[dict[str, Any], dict[str, int]]:
    base_score = scorer_for(load_calibration(CALIBRATION))
    repos = der.load_repos(args, base_score)
    items, sources = ssr.labelled(label_args)
    ctx = {
        "repos": repos,
        "variant_files": args.variant_files,
        "pair_sources": der.load_pair_sources(args),
        "label_items": items,
        "label_sources": sources,
        "dataset": default_dataset(),
    }
    return ctx, {k: len(v) for k, v in repos.items()}


def ships_problems(results: list[tuple[str, Any, Any]], ships: list[str]) -> list[str]:
    by_name = {n: r for n, _, r in results}
    return [
        f"{name} ships on with pair false positive {de.fmt(by_name[name]['pair_fp'])} over 0.10"
        for name in ships
        if (by_name[name]["pair_fp"]["rate"] or 0) > me.PAIR_FP_BUDGET
    ]


if __name__ == "__main__":
    raise SystemExit(main())
