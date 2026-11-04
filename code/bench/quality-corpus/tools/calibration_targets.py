"""Evaluate the calibration targets Q1, Q1m, Q2, Q4, Q5 per language (no model calls).

Inputs: a panel-format dataset dir (items, units, manifest-listed labels), item
scores (`--scores scores.jsonl`, else computed in process with the calibration),
the mutation-pair and anchor sets (`--mutation-pairs`, `--anchors`, else built
from the dev split in process) and a calibration TOML. Reads dev and regression
items only; any other split raises. Output is JSON: per language, every rate
carries n, the point estimate and a task-cluster bootstrap interval, plus a
pass flag with the unmet requirements named. When no decisive panel pair exists
the language reports `labels not ready`; nothing is fabricated.

Q5 bands come from `p65` and `p10` (score points) in the language's
`[language.L.validation]` table; without them the band check is unavailable.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parents[3]
for _path in (ROOT / "code/src", ROOT / "dev/src", TOOLS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import anchor_set  # noqa: E402, RUF100
import mutation_pairs  # noqa: E402, RUF100
import score_dataset  # noqa: E402, RUF100
from varde_code.quality_score import score_scope  # noqa: E402, RUF100
from varde_code.quality_score.calibration import (  # noqa: E402, RUF100
    Calibration,
    load_calibration,
)
from varde_code.quality_score.fixedpoint.arithmetic import MICRO  # noqa: E402, RUF100
from varde_dev.calibrate.reports import (  # noqa: E402, RUF100
    accuracy,
    cluster_bootstrap_interval,
)
from varde_dev.calibrate.reports.dataset import read_dataset_files  # noqa: E402, RUF100
from varde_dev.calibrate.reports.tables import build_report  # noqa: E402, RUF100

ALLOWED_SPLITS = frozenset({"dev", "regression"})
LABELLED = frozenset({"unanimous", "decisive"})
MONOLITH_VARIANT = "monolith"
STRUCTURED_CATEGORY = "a"
SPLIT_CATEGORY = "b"
MARGIN_POINTS = 10
LABELLED_RATE_FLOOR = 0.60
POOLED_PAIR_FLOOR = 40
TARGETS = {"q1": 0.95, "variant": 0.90, "q1m": 0.90, "q2": 0.90, "q4": 0.95, "q5": 0.90}
MARGIN_SHARE_TARGET = 0.90
POOLED_BOUNDS = {"q1": 0.85, "q1m": 0.80, "q2": 0.82}
Win = tuple[str, bool]  # (cluster id, did the score order the pair as expected)


def require_allowed(rows: Iterable[Mapping[str, Any]], what: str) -> None:
    for row in rows:
        split = row.get("split")
        if split is not None and split not in ALLOWED_SPLITS:
            raise ValueError(
                f"{what} {row.get('id')} is in split {split!r}, not dev or regression"
            )


def rate(
    wins: Sequence[Win], *, seed: int = 0, replicates: int = 2000
) -> dict[str, Any]:
    """n, wins, point estimate and cluster-bootstrap 95% interval over clusters."""
    if not wins:
        return {"n": 0, "wins": 0, "rate": None, "bootstrap_95": None, "clusters": 0}
    clusters: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for cluster, win in wins:
        clusters[cluster].append(("1", "1" if win else "0"))
    low, high = cluster_bootstrap_interval(
        [clusters[key] for key in sorted(clusters)],
        accuracy,
        seed=seed,
        replicates=replicates,
    )
    total = sum(win for _, win in wins)
    return {
        "n": len(wins),
        "wins": total,
        "rate": total / len(wins),
        "bootstrap_95": [low, high],
        "clusters": len(clusters),
    }


def meets(rate_row: Mapping[str, Any], target: float) -> bool:
    return rate_row["rate"] is not None and rate_row["rate"] >= target


def preferred_other(
    row: Mapping[str, Any], item_ids: Mapping[str, Sequence[str]]
) -> tuple[str, str]:
    first, second = item_ids[row["unit_id"]]
    return (first, second) if row["panel_preference"] == "A" else (second, first)


def labelled_pairs(
    panel: Sequence[Mapping[str, Any]],
    item_ids: Mapping[str, Sequence[str]],
    scores: Mapping[str, int],
) -> list[dict[str, Any]]:
    """Decisive panel pairs whose two items are both scored; win = preferred higher."""
    pairs = []
    for row in panel:
        if row["panel_class"] not in LABELLED:
            continue
        preferred, other = preferred_other(row, item_ids)
        if preferred not in scores or other not in scores:
            continue
        pairs.append(
            {
                **row,
                "win": scores[preferred] > scores[other],
                "margin": (scores[preferred] - scores[other]) / MICRO,
            }
        )
    return pairs


def lens_one(lens: str) -> bool:
    return lens.lower().replace("lens", "").strip("-_ ") == "1"


def lens_pair_wins(pairs: Sequence[Mapping[str, Any]]) -> dict[str, list[Win]]:
    """Per lens pair: pairs where both lenses voted one side; win = score agrees."""
    wins: dict[str, list[Win]] = defaultdict(list)
    for pair in pairs:
        votes = {vote["lens"]: vote["vote"] for vote in pair["vote_vector"]}
        lenses = sorted(votes)
        for index, left in enumerate(lenses):
            for right in lenses[index + 1 :]:
                if votes[left] == votes[right] and votes[left] in {"A", "B"}:
                    agreed = votes[left] == pair["panel_preference"]
                    wins[f"{left}+{right}"].append(
                        (pair["task_id"], pair["win"] == agreed)
                    )
    return wins


def wins_of(pairs: Iterable[Mapping[str, Any]]) -> list[Win]:
    return [(pair["task_id"], pair["win"]) for pair in pairs]


def labelled_rates(panel: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Labelled rate per category-b variant over all panel rows, labelled or not."""
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row in panel:
        if row["category"] != SPLIT_CATEGORY:
            continue
        totals[row["variant"]][0] += 1
        totals[row["variant"]][1] += row["panel_class"] in LABELLED
    return {
        variant: {
            "total": total,
            "labelled": labelled,
            "labelled_rate": labelled / total,
        }
        for variant, (total, labelled) in sorted(totals.items())
    }


def q1_block(
    pairs: Sequence[Mapping[str, Any]], panel: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    rates = labelled_rates(panel)
    split_pairs = [
        p
        for p in pairs
        if p["category"] == SPLIT_CATEGORY and p["variant"] != MONOLITH_VARIANT
    ]
    variants = {}
    for variant in sorted({p["variant"] for p in split_pairs}):
        info = rates.get(variant, {"labelled_rate": 0.0})
        established = info["labelled_rate"] >= LABELLED_RATE_FLOOR
        row = rate(wins_of(p for p in split_pairs if p["variant"] == variant))
        variants[variant] = {**info, **row, "established": established}
    pooled_pairs = [p for p in split_pairs if variants[p["variant"]]["established"]]
    margins = [p["margin"] >= MARGIN_POINTS for p in pooled_pairs]
    return {
        "variants": variants,
        "pooled": rate(wins_of(pooled_pairs)),
        "margin_10_share": {
            "n": len(margins),
            "share": sum(margins) / len(margins) if margins else None,
        },
    }


def q1_unmet(block: Mapping[str, Any]) -> list[str]:
    established = {name: v for name, v in block["variants"].items() if v["established"]}
    if not established:
        return ["Q1: no variant established (labelled rate under 0.60 or no pairs)"]
    unmet = []
    if not meets(block["pooled"], TARGETS["q1"]):
        unmet.append("Q1 pooled rate under 0.95")
    unmet += [
        f"Q1 variant {name} under 0.90"
        for name, v in established.items()
        if not meets(v, TARGETS["variant"])
    ]
    share = block["margin_10_share"]["share"]
    if share is None or share < MARGIN_SHARE_TARGET:
        unmet.append("Q1 margin of 10 points held in under 90% of pairs")
    return unmet


def q2_block(pairs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    structured = [p for p in pairs if p["category"] == STRUCTURED_CATEGORY]
    per_lens_pair = {
        name: rate(w) for name, w in sorted(lens_pair_wins(structured).items())
    }
    lens_one_met = any(
        meets(row, TARGETS["q2"])
        for name, row in per_lens_pair.items()
        if any(lens_one(lens) for lens in name.split("+"))
    )
    return {
        "pooled": rate(wins_of(structured)),
        "lens_pairs": per_lens_pair,
        "lens_one_pair_meets": lens_one_met,
    }


def score_points(calibration: Calibration, facts: Mapping[str, Any]) -> int | None:
    file = score_scope([dict(facts)], calibration).files[0]
    if file.excluded or file.not_applicable or file.tokens <= 0:
        return None
    return file.score


def q4_block(
    pairs: Sequence[Mapping[str, Any]], calibration: Calibration
) -> dict[str, Any]:
    wins: list[Win] = []
    unscored = 0
    for pair in pairs:
        original = score_points(calibration, pair["original"])
        mutated = score_points(calibration, pair["mutated"])
        if original is None or mutated is None:
            unscored += 1
            continue
        wins.append((pair["item_id"], mutated < original))
    return {**rate(wins), "unscored": unscored}


def anchor_scores(
    anchors: Sequence[Mapping[str, Any]], calibration: Calibration
) -> list[dict[str, Any]]:
    scored = []
    for anchor in anchors:
        row, _ = score_dataset.score_item({**anchor, "split": "dev"}, calibration)
        if row is not None:
            scored.append(
                {
                    "couple": anchor["couple"],
                    "role": anchor["role"],
                    "points": row["score"] / MICRO,
                }
            )
    return scored


def q5_block(
    scored: Sequence[Mapping[str, Any]], validation: Mapping[str, Any]
) -> dict[str, Any]:
    excellent = [a["points"] for a in scored if a["role"] == "excellent"]
    poor = [a["points"] for a in scored if a["role"] == "poor"]
    inverted = bool(excellent and poor and min(excellent) < max(poor))
    p65, p10 = validation.get("p65"), validation.get("p10")
    if p65 is None or p10 is None or not scored:
        return {
            "n": len(scored),
            "in_band": None,
            "rate": None,
            "excellent_below_poor": inverted,
            "bands": None,
        }
    inside = sum(a["points"] >= p65 for a in scored if a["role"] == "excellent")
    inside += sum(a["points"] <= p10 for a in scored if a["role"] == "poor")
    return {
        "n": len(scored),
        "in_band": inside,
        "rate": inside / len(scored),
        "excellent_below_poor": inverted,
        "bands": {"p65": p65, "p10": p10},
    }


def language_report(
    language: str,
    panel: Sequence[Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
    mutation: Sequence[Mapping[str, Any]],
    anchors: Sequence[Mapping[str, Any]],
    calibration: Calibration,
) -> dict[str, Any]:
    entry = calibration.languages[language]
    q1 = q1_block(pairs, panel)
    q1m = rate(
        wins_of(
            p
            for p in pairs
            if p["category"] == SPLIT_CATEGORY and p["variant"] == MONOLITH_VARIANT
        )
    )
    q2 = q2_block(pairs)
    q4 = q4_block(mutation, calibration)
    q5 = q5_block(anchor_scores(anchors, calibration), entry.validation)
    labels_ready = bool(pairs)
    unmet = [] if labels_ready else ["labels not ready"]
    if labels_ready:
        unmet += q1_unmet(q1)
        unmet += [] if meets(q1m, TARGETS["q1m"]) else ["Q1m under 0.90 or no pairs"]
        unmet += (
            [] if meets(q2["pooled"], TARGETS["q2"]) else ["Q2 under 0.90 or no pairs"]
        )
        unmet += (
            []
            if q2["lens_one_pair_meets"]
            else ["Q2: no lens pair including lens 1 meets 0.90"]
        )
    unmet += [] if meets(q4, TARGETS["q4"]) else ["Q4 under 0.95 or no pairs"]
    unmet += _q5_unmet(q5)
    return {
        "language": language,
        "state": entry.state,
        "labels": "ready" if labels_ready else "labels not ready",
        "decisive_pairs": len(pairs),
        "q1": q1,
        "q1m": q1m,
        "q2": q2,
        "q4": q4,
        "q5": q5,
        "unmet": unmet,
        "pass": not unmet,
    }


def _q5_unmet(q5: Mapping[str, Any]) -> list[str]:
    unmet = []
    if q5["rate"] is None:
        unmet.append("Q5 bands or anchors unavailable")
    elif q5["rate"] < TARGETS["q5"]:
        unmet.append("Q5 under 0.90 of anchors inside bands")
    if q5["excellent_below_poor"]:
        unmet.append("Q5: an excellent anchor scores below a poor one")
    return unmet


def pooled_block(pairs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Three-language pooled bootstrap bounds; gated at 40+ decisive (b) pairs."""
    split = [p for p in pairs if p["category"] == SPLIT_CATEGORY]
    parts = {
        "q1": rate(wins_of(p for p in split if p["variant"] != MONOLITH_VARIANT)),
        "q1m": rate(wins_of(p for p in split if p["variant"] == MONOLITH_VARIANT)),
        "q2": rate(wins_of(p for p in pairs if p["category"] == STRUCTURED_CATEGORY)),
    }
    gated = len(split) >= POOLED_PAIR_FLOOR
    failed = [
        name
        for name, row in parts.items()
        if gated
        and row["bootstrap_95"] is not None
        and row["bootstrap_95"][0] < POOLED_BOUNDS[name]
    ]
    return {
        "decisive_b_pairs": len(split),
        "gated": gated,
        **parts,
        "failed_bounds": failed,
        "pass": not failed,
    }


def load_scores(path: Path) -> dict[str, int]:
    with path.open(encoding="utf-8") as handle:
        return {
            row["id"]: row["score"]
            for row in map(json.loads, filter(str.strip, handle))
        }


def evaluate(
    dataset: Path,
    calibration: Calibration,
    scores: Mapping[str, int] | None,
    mutation: Sequence[Mapping[str, Any]],
    anchors: Sequence[Mapping[str, Any]],
    languages: Sequence[str],
) -> dict[str, Any]:
    files = read_dataset_files(dataset)
    require_allowed(files["items"], "item")
    require_allowed(files["units"], "unit")
    item_ids = {unit["id"]: unit["item_ids"] for unit in files["units"]}
    if scores is None:
        rows, _ = score_dataset.score_dataset(
            [item for item in files["items"] if item["language"] in languages],
            calibration,
        )
        scores = {row["id"]: row["score"] for row in rows}
    panel = build_report(files["labels"], files["units"], files["items"])["panel"]
    reports = {}
    pooled_pairs: list[dict[str, Any]] = []
    for language in languages:
        rows = [row for row in panel if row["language"] == language]
        language_pairs = labelled_pairs(rows, item_ids, scores)
        reports[language] = language_report(
            language,
            rows,
            language_pairs,
            [p for p in mutation if p["language"] == language],
            [a for a in anchors if a["language"] == language],
            calibration,
        )
        pooled_pairs += language_pairs
    return {
        "calibration": calibration.id,
        "languages": reports,
        "pooled": pooled_block(pooled_pairs),
    }


def check_exit(result: Mapping[str, Any]) -> int:
    failing = [
        name
        for name, report in result["languages"].items()
        if report["state"] != "report-only" and not report["pass"]
    ]
    for name in failing:
        print(
            f"FAIL {name}: {'; '.join(result['languages'][name]['unmet'])}",
            file=sys.stderr,
        )
    pooled_failed = not result["pooled"]["pass"]
    if pooled_failed:
        print(f"FAIL pooled: {result['pooled']['failed_bounds']}", file=sys.stderr)
    return 1 if failing or pooled_failed else 0


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def default_mutation_pairs(
    dataset: Path, languages: Sequence[str]
) -> list[dict[str, Any]]:
    items = score_dataset.read_items(dataset, mutation_pairs.ALLOWED_SPLITS)
    return mutation_pairs.build_pairs(items, frozenset(languages))[0]


def default_anchors(languages: Sequence[str]) -> list[dict[str, Any]]:
    return anchor_set.build_anchors(
        anchor_set.ITEMS, list(languages), anchor_set.load_assignments()
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=score_dataset.default_dataset())
    parser.add_argument("--scores", type=Path, default=None)
    parser.add_argument("--mutation-pairs", type=Path, default=None)
    parser.add_argument("--anchors", type=Path, default=None)
    parser.add_argument("--languages", default=anchor_set.DEFAULT_LANGUAGES)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    languages = [name.strip() for name in args.languages.split(",") if name.strip()]
    mutation = (
        read_jsonl(args.mutation_pairs)
        if args.mutation_pairs
        else default_mutation_pairs(args.dataset, languages)
    )
    anchors = read_jsonl(args.anchors) if args.anchors else default_anchors(languages)
    require_allowed(mutation, "mutation pair")
    require_allowed(anchors, "anchor")
    scores = load_scores(args.scores) if args.scores else None
    result = evaluate(
        args.dataset,
        load_calibration(args.calibration),
        scores,
        mutation,
        anchors,
        languages,
    )
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return check_exit(result) if args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
