"""Read-only driver for tuning against the shipped sample corpus.

Every margin comes from re-scoring the facts at the strengths under test: the
component debts are nonlinear in A, wL and w, so vectors extracted at one
calibration cannot be rescaled to another.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
CODE_SRC = ROOT / "code/src"
for _path in (CODE_SRC, Path(__file__).resolve().parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from exact_scoring import (  # noqa: E402, RUF100
    CONTROL,
    TARGET,
    SampleFacts,
    at_strengths,
    sample_debts,
    worst_margin,
)
from varde_code.quality_pass.facts import extract_facts  # noqa: E402, RUF100
from varde_code.quality_score.calibration import Calibration, load_calibration  # noqa: E402, RUF100
from varde_code.quality_score.fixedpoint import MICRO  # noqa: E402, RUF100
from varde_code.quality_score.samples import load_sample  # noqa: E402, RUF100
from varde_code.quality_score.tuner import fit_exact  # noqa: E402, RUF100

CALIBRATION_PATH = CODE_SRC / "varde_code/quality_score/calibration/cal-1.toml"
SAMPLES_PATH = CODE_SRC / "varde_code/quality_score/samples"
SEEDED_PATH = ROOT / "code/bench/quality-corpus/seeded"
GAMING_NAMES = ("tiny", "padded", "monolith", "namematched")
GAMING_PREFIX = "gaming:"
DEFAULT_LANGUAGES = "python,typescript,csharp"
SUFFIXES = {
    "python": ".py",
    "typescript": ".ts",
    "csharp": ".cs",
    "java": ".java",
    "go": ".go",
}
GRAMMAR_HINT = (
    " (set VARDE_TREE_SITTER_CACHE_DIR to a writable, prefetched grammar cache)"
)

# Fixed before any fold ran (design Amendment A2, t8): the upper bound is the
# shipped limits.strength ceiling; the lower bound is one grid step above zero,
# the smallest positive strength, so no region is cut off by a bound.
# `structure` is not searched (no constraint uses it); it keeps its start value.
SEARCH_BOUNDS = {
    "A": (50_000, 2_000_000),
    "wL": (50_000, 2_000_000),
    "w": (50_000, 2_000_000),
}
FitFunction = Callable[[list[SampleFacts], Calibration], dict[str, int]]


def split_by_scope(
    samples: list[SampleFacts], in_scope: frozenset[str]
) -> tuple[list[SampleFacts], list[SampleFacts]]:
    """Split samples into fitted (in-scope languages) and informational."""
    scoped = [sample for sample in samples if sample.language in in_scope]
    info = [sample for sample in samples if sample.language not in in_scope]
    return scoped, info


def variants_dir(language: str, sample_id: str) -> Path:
    """Gaming variants of one sample: its own directory, else the language's."""
    language_dir = SEEDED_PATH / language
    return (
        language_dir / sample_id
        if (language_dir / sample_id).is_dir()
        else language_dir
    )


def default_fit(samples: list[SampleFacts], calibration: Calibration) -> dict[str, int]:
    """Exact-scoring search maximizing the smallest margin (plan Design)."""
    ordered = list(samples)

    def worst(strengths: Mapping[str, int], floor: int) -> int:
        return worst_margin(ordered, at_strengths(calibration, strengths), floor)

    return fit_exact(worst, calibration.global_strengths, SEARCH_BOUNDS).strengths


def constraint_rows(debts: dict[str, int]) -> list[dict[str, Any]]:
    """Absolute margin (challenger debt - target debt) of every challenger."""
    return [
        {
            "challenger": name,
            "margin": value - debts[TARGET],
            "passed": value - debts[TARGET] >= 0,
        }
        for name, value in sorted(debts.items())
        if name not in (TARGET, CONTROL)
    ]


def loo_folds(
    samples: list[SampleFacts],
    calibration: Calibration,
    fit: FitFunction = default_fit,
) -> list[dict[str, Any]]:
    """Leave-one-sample-out: fit on the others, score the held-out sample.

    A fold holds out a whole sample; its language siblings stay in training.
    Fold results are evidence only; no constant is chosen from them.
    """
    folds = []
    for held in sorted(samples, key=lambda item: item.id):
        train = [item for item in samples if item.id != held.id]
        if not train:
            continue
        strengths = fit(train, calibration)
        debts = sample_debts(held, at_strengths(calibration, strengths))
        folds.append(
            {
                "held_out": held.id,
                "strengths": strengths,
                "target": debts[TARGET],
                "margins": constraint_rows(debts),
            }
        )
    return folds


EVIDENCE_LIMITS = (
    "Evidence limits: one fold per sample (about 10 constraints each), shared "
    "global strengths. Search bounds and grid step were fixed after exploratory "
    "scans that saw the first three samples, so LOO checks that the fit does not "
    "hinge on one sample; it is not an unbiased generalization estimate. "
    "Margins are absolute micro-debt scored at the stated strengths; the fit "
    "maximizes the smallest margin. Thin means 0 <= margin < 1% of the target's debt."
)


def thin_suffix(margin: int, target: int) -> str:
    """Flag a passing margin below 1% of the target's debt."""
    return " thin" if 0 <= margin < target // 100 else ""


def check_failures(report: dict[str, Any]) -> list[str]:
    """Name every in-sample or held-out constraint with a negative margin."""
    failures = [
        f"in-sample {sample['id']} {item['challenger']} margin {item['margin']:+}"
        for sample in report["samples"]
        for item in sample["constraints"]
        if item["margin"] < 0
    ]
    failures.extend(
        f"loo {fold['held_out']} {item['challenger']} margin {item['margin']:+}"
        for fold in report.get("loo", [])
        for item in fold["margins"]
        if item["margin"] < 0
    )
    return failures


def informational_row(sample: SampleFacts, calibration: Calibration) -> dict[str, Any]:
    """Score an out-of-scope sample at the fitted strengths; no constraint applies."""
    rows = constraint_rows(sample_debts(sample, calibration))
    worst = min(
        rows, key=lambda item: (item["margin"], item["challenger"]), default=None
    )
    return {
        "id": sample.id,
        "language": sample.language,
        "worst_challenger": worst["challenger"] if worst else "",
        "worst_margin": worst["margin"] if worst else None,
    }


def sample_report(sample: SampleFacts, calibration: Calibration) -> dict[str, Any]:
    debts = sample_debts(sample, calibration)
    target = debts[TARGET]
    control = debts.get(CONTROL)
    return {
        "id": sample.id,
        "target_weighted_debt": target,
        "versions": {
            name: {"weighted_debt": value, "vs_smoothed": value - target}
            for name, value in sorted(debts.items())
            if name not in (TARGET, CONTROL) and not name.startswith(GAMING_PREFIX)
        },
        "constraints": constraint_rows(debts),
        "sizematched_control": (
            None
            if control is None
            else {"weighted_debt": control, "vs_smoothed": control - target}
        ),
    }


def build_report(
    samples: list[SampleFacts],
    calibration: Calibration,
    strengths: dict[str, int],
    errors: list[dict[str, str]],
    informational: list[SampleFacts] | None = None,
) -> dict[str, Any]:
    """Build a JSON-ready report; every debt is scored at `strengths`."""
    scored = at_strengths(calibration, strengths)
    reports = [
        sample_report(sample, scored)
        for sample in sorted(samples, key=lambda item: item.id)
    ]
    failing = any(
        item["margin"] < 0 for report in reports for item in report["constraints"]
    )
    starting = calibration.global_strengths
    return {
        "status": "not validated" if failing or not samples else "validated",
        "validated": bool(samples) and not failing,
        "resulting_calibration": strengths,
        "calibration": {"id": calibration.id, "sha256": calibration.source_sha256},
        "starting_calibration": dict(starting),
        "changed_values": {
            key: {"from": value, "to": strengths[key]}
            for key, value in sorted(starting.items())
            if strengths.get(key) != value
        },
        "samples": reports,
        "extraction_errors": errors,
        "informational": [
            informational_row(item, scored) for item in informational or []
        ],
        "loo": [],
    }


def _facts(path: Path, language: str) -> dict[str, Any]:
    return extract_facts(path.read_bytes(), language, path.as_posix())


def load_sample_facts() -> tuple[list[SampleFacts], list[dict[str, str]]]:
    samples: list[SampleFacts] = []
    errors: list[dict[str, str]] = []
    for directory in sorted(SAMPLES_PATH.iterdir()):
        if not directory.is_dir() or not (directory / "sample.toml").is_file():
            continue
        try:
            sample = load_sample(directory.name, package_root=SAMPLES_PATH)
            language = sample.language
            language_dir = variants_dir(language, directory.name)
            suffix = SUFFIXES[language]
            challengers = {
                name: _facts(Path(path), language)
                for name, path in sample.versions.items()
                if name != TARGET
            }
            challengers.update(
                {
                    f"{GAMING_PREFIX}{name}": _facts(
                        language_dir / f"{name}{suffix}", language
                    )
                    for name in GAMING_NAMES
                }
            )
            samples.append(
                SampleFacts(
                    directory.name,
                    language,
                    _facts(Path(sample.versions[TARGET]), language),
                    challengers,
                    _facts(language_dir / f"{CONTROL}{suffix}", language),
                )
            )
        except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            message = f"{type(exc).__name__}: {exc}"
            if "grammar" in message:
                message += GRAMMAR_HINT
            errors.append({"sample_id": directory.name, "error": message})
    return samples, errors


def render_text(report: dict[str, Any]) -> str:
    lines = [
        (
            f"Calibration: {report['calibration']['id']} "
            f"sha256 {report['calibration']['sha256']}"
        ),
        f"Tuning (exact scoring): {report['status']}",
        "Fitted strengths: "
        + ", ".join(
            f"{key}={value / MICRO:g}"
            for key, value in sorted(report["resulting_calibration"].items())
            if key in SEARCH_BOUNDS
        ),
    ]
    for sample in report["samples"]:
        lines.append(f"\n{sample['id']} target={sample['target_weighted_debt']}")
        for name, value in sample["versions"].items():
            lines.append(
                f"  version {name}: {value['weighted_debt']} "
                f"(vs smoothed {value['vs_smoothed']:+})"
            )
        lines.extend(
            f"  constraint {item['challenger']}: margin {item['margin']:+} "
            f"({'pass' if item['passed'] else 'FAIL'})"
            f"{thin_suffix(item['margin'], sample['target_weighted_debt'])}"
            for item in sample["constraints"]
        )
        control = sample["sizematched_control"]
        if control is not None:
            lines.append(
                f"  sizematched control: {control['weighted_debt']} "
                f"(vs smoothed {control['vs_smoothed']:+}; informational)"
            )
    lines.extend(
        f"info: {item['id']} ({item['language']}) worst "
        f"{item['worst_challenger'] or 'none'} margin {item['worst_margin']:+}"
        " (informational; no constraint)"
        if item["worst_margin"] is not None
        else f"info: {item['id']} ({item['language']}) no challengers"
        for item in report["informational"]
    )
    for fold in report["loo"]:
        fitted = ", ".join(
            f"{key}={fold['strengths'][key] / MICRO:g}" for key in SEARCH_BOUNDS
        )
        lines.append(f"\nLOO held out {fold['held_out']} (fit {fitted})")
        lines.extend(
            f"  loo constraint {item['challenger']}: margin {item['margin']:+} "
            f"({'pass' if item['passed'] else 'FAIL'})"
            f"{thin_suffix(item['margin'], fold['target'])}"
            for item in fold["margins"]
        )
    if report["extraction_errors"]:
        lines.append("\nExtraction errors:")
        lines.extend(
            f"  {item['sample_id']}: {item['error']}"
            for item in report["extraction_errors"]
        )
    lines.append("\nCalibration changes:")
    changes = report["changed_values"]
    lines.extend(
        f"  {key}: {value['from'] / MICRO:g} -> {value['to'] / MICRO:g}"
        for key, value in changes.items()
    )
    if not changes:
        lines.append("  none")
    lines.append("\n" + EVIDENCE_LIMITS)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="print machine-readable JSON"
    )
    parser.add_argument(
        "--languages",
        default=DEFAULT_LANGUAGES,
        help="comma-separated languages to fit; other languages print as info: rows",
    )
    parser.add_argument(
        "--calibration",
        type=Path,
        default=CALIBRATION_PATH,
        help="calibration TOML to start from and score with "
        "(default: cal-2 from cal-1.toml)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 when any in-sample or leave-one-out margin is negative",
    )
    args = parser.parse_args()
    in_scope = frozenset(
        item.strip() for item in args.languages.split(",") if item.strip()
    )
    calibration = load_calibration(args.calibration)
    loaded, errors = load_sample_facts()
    try:
        scoped, info_samples = split_by_scope(loaded, in_scope)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    strengths = (
        default_fit(scoped, calibration)
        if len(scoped) >= 2
        else dict(calibration.global_strengths)
    )
    report = build_report(scoped, calibration, strengths, errors, info_samples)
    report["loo"] = loo_folds(scoped, calibration) if len(scoped) >= 3 else []
    print(
        json.dumps(report, indent=2, sort_keys=True)
        if args.json
        else render_text(report)
    )
    failures = check_failures(report) if args.check else []
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr if args.json else sys.stdout)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
