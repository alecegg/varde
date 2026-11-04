"""Q4 (mutation pairs) and Q5 (anchors) of a calibration, dev split only.

Q4: share of pairs whose mutated side scores strictly lower (pass >= 0.95 per
language). Q5: share of anchors in band (excellent at or above X, poor below X;
pass >= 0.90) and no excellent anchor below any poor anchor. Scores are exact
fixed-point values of the installed scorer under the named calibration. No
model call. A miss is reported, never tuned away.

    uv run python baseline_q4q5.py --check --calibration cal-1.toml
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import anchor_set  # noqa: E402, RUF100
import mutation_pairs  # noqa: E402, RUF100
from score_dataset import default_dataset, item_path, read_items  # noqa: E402, RUF100
from varde_code.quality_pass.facts import extract_facts  # noqa: E402, RUF100
from varde_code.quality_score.calibration import Calibration, load_calibration  # noqa: E402, RUF100
from varde_code.quality_score.scoring import score_scope  # noqa: E402, RUF100

Q4_MIN = 0.95
Q5_MIN = 0.90
MICRO = 1_000_000
LANGUAGES = ("python", "typescript", "csharp")
PLAN_NOTES = Path(
    "/Users/alec/source/agent-memory/projects/varde-py/working/plans"
    "/2026-10-31-vqs-example-baseline/notes"
)


# ---- pure logic -------------------------------------------------------------


def require_dev(rows: Sequence[Mapping[str, Any]]) -> None:
    bad = sorted({str(r.get("id")) for r in rows if r.get("split") != "dev"})
    if bad:
        raise ValueError(f"Q4/Q5 use the dev split only; not dev: {bad}")


def rate(hits: int, n: int) -> float | None:
    return round(hits / n, 4) if n else None


def q4_result(scores: Sequence[tuple[int | None, int | None]]) -> dict[str, Any]:
    """scores: (original, mutated) micro-points; pairs with no original are skipped."""
    scored = [(o, m) for o, m in scores if o is not None]
    lower = sum(1 for o, m in scored if m is not None and m < o)
    value = rate(lower, len(scored))
    return {
        "n": len(scored),
        "hits": lower,
        "skipped": len(scores) - len(scored),
        "rate": value,
        "pass": value is not None and lower >= Q4_MIN * len(scored),
    }


def q5_result(excellent: Sequence[int], poor: Sequence[int], x: int) -> dict[str, Any]:
    """Anchor scores in micro-points against the gate value x in micro-points."""
    n = len(excellent) + len(poor)
    in_band = sum(s >= x for s in excellent) + sum(s < x for s in poor)
    inversions = (
        sum(1 for e in excellent for p in poor if e < p) if excellent and poor else 0
    )
    value = rate(in_band, n)
    return {
        "n": n,
        "hits": in_band,
        "n_excellent": len(excellent),
        "n_poor": len(poor),
        "x": x / MICRO,
        "inversions": inversions,
        "rate": value,
        "pass": value is not None and in_band >= Q5_MIN * n and inversions == 0,
    }


def failures(results: Mapping[str, Mapping[str, Any]]) -> list[str]:
    lines = []
    for language, entry in results.items():
        for name in ("q4", "q5"):
            part = entry[name]
            if not part["pass"]:
                extra = f", {part['inversions']} inversions" if name == "q5" else ""
                lines.append(
                    f"{language} {name.upper()} rate {part['rate']} "
                    f"({part['hits']}/{part['n']}){extra}"
                )
    return lines


# ---- scoring ----------------------------------------------------------------


def micro_score(facts: dict[str, Any], calibration: Calibration) -> int | None:
    try:
        scope = score_scope([facts], calibration)
    except ValueError, RuntimeError, KeyError, TypeError:
        return None
    file = scope.files[0] if scope.files else None
    if file is None or file.excluded or file.not_applicable or file.tokens <= 0:
        return None
    return file.score


def q4_scores(
    language: str, calibration: Calibration, dataset: Path
) -> tuple[list, list[str]]:
    items = read_items(dataset, frozenset({"dev"}))
    pairs, _ = mutation_pairs.build_pairs(items, frozenset({language}))
    require_dev(pairs)
    return [
        (
            micro_score(p["original"], calibration),
            micro_score(p["mutated"], calibration),
        )
        for p in pairs
    ], [p["mutation"] for p in pairs]


def q5_scores(language: str, calibration: Calibration) -> tuple[list[int], list[int]]:
    rows = anchor_set.build_anchors(
        anchor_set.ITEMS, [language], anchor_set.load_assignments()
    )
    require_dev(rows)
    by_role: dict[str, list[int]] = {"excellent": [], "poor": []}
    for row in rows:
        facts = extract_facts(row["text"], language, item_path(row))
        score = micro_score(facts, calibration)
        if score is not None:
            by_role[row["role"]].append(score)
    return by_role["excellent"], by_role["poor"]


def evaluate(calibration: Calibration, dataset: Path) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for language in LANGUAGES:
        x = calibration.languages[language].threshold_x
        excellent, poor = q5_scores(language, calibration)
        pairs, names = q4_scores(language, calibration, dataset)
        by_mutation = {
            name: q4_result([s for s, n in zip(pairs, names, strict=True) if n == name])
            for name in sorted(set(names))
        }
        results[language] = {
            "q4": {**q4_result(pairs), "by_mutation": by_mutation},
            "q5": q5_result(excellent, poor, x),
        }
    return results


# ---- output -----------------------------------------------------------------


def flat_json(results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """One entry per language/question with n and rate, as the check asserts."""
    return {
        f"{language}:{name}": part
        for language, entry in results.items()
        for name, part in entry.items()
    }


def report_lines(results: Mapping[str, Mapping[str, Any]], calibration_id: str) -> str:
    lines = [f"# Q4/Q5 on {calibration_id} (dev split, no model calls)", ""]
    lines += ["| language | Q4 pairs lower | Q4 n | Q5 in band | Q5 n | inversions |"]
    lines += ["| --- | ---: | ---: | ---: | ---: | ---: |"]
    for language, entry in results.items():
        q4, q5 = entry["q4"], entry["q5"]
        lines.append(
            f"| {language} | {q4['rate']} ({'pass' if q4['pass'] else 'MISS'}) | "
            f"{q4['n']} | {q5['rate']} ({'pass' if q5['pass'] else 'MISS'}) | "
            f"{q5['n']} | {q5['inversions']} |"
        )
    lines += ["", f"Pass: Q4 >= {Q4_MIN}, Q5 >= {Q5_MIN} with no inversion.", ""]
    lines += ["", "Q4 rate by mutation (diagnostic):", ""]
    for language, entry in results.items():
        parts = [f"{k} {v['rate']}" for k, v in entry["q4"]["by_mutation"].items()]
        lines.append(f"- {language}: " + ", ".join(parts))
    lines += ["Q4 rate by mutation (diagnostic):", ""]
    for language, entry in results.items():
        parts = [f"{k} {v['rate']}" for k, v in entry["q4"]["by_mutation"].items()]
        lines.append(f"- {language}: " + ", ".join(parts))
    missed = failures(results)
    lines.append("")
    lines += ["Misses:"] + [f"- {m}" for m in missed] if missed else ["No misses."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=default_dataset())
    parser.add_argument("--out-dir", type=Path, default=PLAN_NOTES)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    calibration = load_calibration(args.calibration)
    results = evaluate(calibration, args.dataset)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "q4q5.json").write_text(
        json.dumps(flat_json(results), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    text = report_lines(results, calibration.id)
    (args.out_dir / "q4q5.md").write_text(text, encoding="utf-8")
    print(text)
    missed = failures(results)
    if args.check and missed:
        print("Q4/Q5 miss: " + "; ".join(missed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
