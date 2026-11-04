"""Corpus-derived default region presets per language; writes ``cal-1.toml``.

    uv run python region_presets.py --out <cal-1.toml>            # write
    uv run python region_presets.py --check --out <cal-1.toml>    # rebuild and compare

No model call. Per language the default loose region is a corpus quantile per
fitted measure (verified-corpus dev-split functions at pinned SHAs). Python is
anchored by the agreed examples through ``baseline_region.calibrate`` (k = the
number of agreed Python samples), clamped to the corpus [q50, q99]; TypeScript
and C# have no model-written examples, so k = 0 and the default stays. The
global ``dominance`` comes from ``baseline_dominance.derive_dominance`` on the
Python agreed reference. ``X`` is the relative line (10th percentile) of the
language's good-set scores: the corpus dev files, plus the agreed examples for
Python (agreed code alone scores above ordinary repo code, so alone it would
flag about half of real files). ``Y`` and ``cap`` keep the installed ratios. Other
languages are copied from the placeholder and stay ``report-only``. Tuned
``A wL w``, the S curve and the loader are untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pwd
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import baseline_build_cal as bbc
import baseline_dominance as bd
import baseline_index_run as ir
import baseline_measure as bm
import baseline_region as br
import scorer_candidates as sc
import splits
from varde_code.quality_pass.facts import extract_facts
from varde_code.quality_score import refactor_line as rl

USER_CACHE = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".cache/varde/bench"
PLACEHOLDER = bm.DEFAULT_CALIBRATION
CAL_ID = "cal-2"
FORMULA = "vq2"  # sd (delegation) is on; vq1 had every measure strength off
LANGUAGES = ("python", "typescript", "csharp")
MANIFEST_NAME = {"python": "Python", "typescript": "TypeScript", "csharp": "C#"}
# raw_measure row key -> cal-1 key, same as the t11 calibrate step
MEASURES = tuple(br.FITTED)
DEFAULT_PERCENTILE = 99
PLACEHOLDER_P0 = 2
PER_REPO = 60
MICRO = bd.MICRO
PLACEHOLDER_X, PLACEHOLDER_Y = 62, 38  # installed ratio Y/X
PLACEHOLDER_CAP_NUM, PLACEHOLDER_CAP_DEN = 125, 38  # cap = Y * 12.5 / 38
PENDING = "pending constraints"
# Shadow-mode measure keys (t5): thresholds per language, strengths global and off.
# n0 is the corpus q90 of max_nesting from measure_quantiles --check (python 1,
# typescript 1, csharp 0); languages without a corpus keep the python value.
NESTING_Q90 = {"python": 1, "typescript": 1, "csharp": 0}
DEFAULT_NESTING = 1
VAGUE_NAMES_ALLOWED = 0
DELEGATION_SHARE_ALLOWED = "0.333333"  # exact good-file p90 (1/3)
SHADOW_KEYS = ("n0", "nm0", "dg0")
# sd is on at 1.0 (measures_eval, notes/measures-eval.md); sn and sm stay off.
SHADOW_STRENGTHS = {"sn": "0.0", "sm": "0.0", "sd": "1.0"}
SHADOW_LIMITS = {
    "n0": ["0", "50"],
    "nm0": ["0", "50"],
    "dg0": ["0", "1"],
    "sn": ["0", "2.0"],
    "sm": ["0", "2.0"],
    "sd": ["0", "2.0"],
}

Record = Mapping[str, Any]
Rows = Sequence[Mapping[str, Any]]


@dataclass(frozen=True)
class LanguageInputs:
    """Everything one language's preset depends on."""

    corpus: Mapping[str, Sequence[int]]  # raw measure -> corpus function values
    corpus_files: int
    examples: Sequence[Rows]  # raw rows per agreed example (empty: k = 0)
    agreed_records: Sequence[Record]  # facts of the agreed examples (dominance, check)
    reference_records: Sequence[Record]  # good set whose scores give X (pooled)


# ---- pure derivation --------------------------------------------------------


def default_region(
    placeholder: Mapping[str, int],
    corpus: Mapping[str, Sequence[int]],
    percentile: int = DEFAULT_PERCENTILE,
) -> dict[str, int]:
    """Placeholder thresholds with each fitted key at its corpus quantile."""
    region = {k: v for k, v in placeholder.items() if k in br.FITTED.values()}
    region.setdefault("p0", PLACEHOLDER_P0)
    for measure, key in br.FITTED.items():
        anchor = br.nearest_rank(corpus.get(measure, ()), percentile)
        if anchor is not None:
            region[key] = anchor
    return region


def language_region(
    placeholder: Mapping[str, int], inputs: LanguageInputs
) -> dict[str, int]:
    default = default_region(placeholder, inputs.corpus)
    return br.calibrate(default, list(inputs.examples), inputs.corpus)


def tenths(value: float) -> int:
    """Floor of ``value`` in tenths, so a score at the line stays at or above X."""
    return math.floor(Decimal(repr(value)) * 10)


def gate_tenths(line: float) -> tuple[int, int, int]:
    """(X, Y, cap) in tenths, tenths, hundredths; Y and cap keep installed ratios."""
    x = tenths(line)
    y = x * PLACEHOLDER_Y // PLACEHOLDER_X
    cap = y * PLACEHOLDER_CAP_NUM // PLACEHOLDER_CAP_DEN
    if not x > y > 0:
        raise ValueError(f"refactor line {line} gives X={x} Y={y} (need X > Y > 0)")
    return x, y, cap


def decimal_text(value: int, places: int) -> str:
    return f"{Decimal(value).scaleb(-places):.{places}f}"


def dominance_text(strength: int) -> str:
    return f"{Decimal(strength) / MICRO:.2f}"


def score_reference(
    records: Sequence[Record],
    base: bm.Calibration,
    language: str,
    region: br.Region,
    dominance: int,
) -> list[float]:
    calibration = bd.with_region(base, language, region)
    spec = sc.Spec("cal-1", dominance=dominance / MICRO)
    return [sc.candidate_score(record, calibration, spec) for record in records]


# ---- rendering --------------------------------------------------------------


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(value)


def table(name: str, values: Mapping[str, Any]) -> list[str]:
    return [f"[{name}]", *(f"{k} = {toml_value(v)}" for k, v in values.items()), ""]


def language_table(
    placeholder: Mapping[str, Any],
    region: Mapping[str, int] | None,
    gates: tuple[int, int, int] | None,
) -> dict[str, Any]:
    """Placeholder keys in order; fitted thresholds and X, Y, cap replaced."""
    values = {k: v for k, v in placeholder.items() if k != "validation"}
    if region is None or gates is None:
        return values
    out: dict[str, Any] = {}
    for key, value in values.items():
        out[key] = region.get(key, value)
        if key == "t0":
            out["p0"] = region["p0"]
    out["X"], out["Y"], out["cap"] = (
        decimal_text(gates[0], 1),
        decimal_text(gates[1], 1),
        decimal_text(gates[2], 2),
    )
    return out


def shadow_thresholds(language: str) -> dict[str, Any]:
    return {
        "n0": NESTING_Q90.get(language, DEFAULT_NESTING),
        "nm0": VAGUE_NAMES_ALLOWED,
        "dg0": DELEGATION_SHARE_ALLOWED,
    }


def render_cal1(
    base: Mapping[str, Any],
    regions: Mapping[str, Mapping[str, int]],
    gates: Mapping[str, tuple[int, int, int]],
    dominance: int,
    provenance: Mapping[str, str],
) -> str:
    """The cal-1 text: placeholder copy with v1-language presets and dominance."""
    meta = {
        **base["calibration"],
        "id": CAL_ID,
        "formula": FORMULA,
        "validated": False,
        "anchors": "installed S curve (smap.PLACEHOLDER_ANCHORS), unchanged",
    }
    lines = table("calibration", meta)
    shadow = {"dominance": dominance_text(dominance), **SHADOW_STRENGTHS}
    lines += table("global", {**base["global"], **shadow})
    for language, placeholder in base["language"].items():
        values = language_table(placeholder, regions.get(language), gates.get(language))
        values = {**values, **shadow_thresholds(language)}
        lines += table(f"language.{language}", values)
    for language in base["language"]:
        validation = {
            "state": "report-only",
            "reason": PENDING,
            "provenance": provenance.get(
                language, "copied from the placeholder; not calibrated"
            ),
        }
        lines += table(f"language.{language}.validation", validation)
    for group, entries in base["limits"].items():
        lines += table(f"limits.{group}", entries)
    lines += table("limits.measures", SHADOW_LIMITS)
    return "\n".join(lines).rstrip("\n") + "\n"


def provenance_text(
    language: str, inputs: LanguageInputs, region: Mapping[str, int], k: int
) -> str:
    functions = len(inputs.corpus.get("tokens", ()))
    return (
        f"corpus-derived default region: q{DEFAULT_PERCENTILE} of {functions} "
        f"verified-corpus dev-split functions in {inputs.corpus_files} files "
        f"({language}); k={k} agreed examples (t11 calibrate, clamped to corpus "
        f"q{br.LOW_PERCENTILE}-q{br.HIGH_PERCENTILE}); X is the 10th percentile of "
        f"{len(inputs.reference_records)} good-set scores; Y and cap keep the "
        "installed ratios; not validated"
    )


@dataclass(frozen=True)
class Built:
    text: str
    agreed_scores: Sequence[float]
    x_tenths: Mapping[str, int]


def build(inputs: Mapping[str, LanguageInputs], base_path: Path = PLACEHOLDER) -> Built:
    """Cal-1 text from the per-language inputs (deterministic, no I/O)."""
    base_data = tomllib.loads(base_path.read_text())
    base = bm.load_calibration(base_path)
    regions = {
        language: language_region(base_data["language"][language], inputs[language])
        for language in inputs
    }
    dominance = bd.derive_dominance(
        inputs["python"].agreed_records, regions["python"], base, "python"
    )
    scores = {
        language: score_reference(
            inputs[language].reference_records,
            base,
            language,
            regions[language],
            dominance,
        )
        for language in inputs
    }
    gates = {
        language: gate_tenths(rl.reference_line(scores[language]))
        for language in inputs
    }
    notes = {
        language: provenance_text(
            language,
            inputs[language],
            regions[language],
            len(inputs[language].examples),
        )
        for language in inputs
    }
    text = render_cal1(base_data, regions, gates, dominance, notes)
    agreed = score_reference(
        inputs["python"].agreed_records, base, "python", regions["python"], dominance
    )
    return Built(text, agreed, {language: gates[language][0] for language in gates})


# ---- loading (I/O) ----------------------------------------------------------


def candidate_path(path: str, language: str) -> bool:
    parts = path.split("/")
    in_test_dir = any("test" in part.lower() for part in parts[:-1])
    return (
        path.endswith(bm.SUFFIXES[language])
        and not ir.SKIPPED_PARTS & {p.lower() for p in parts[:-1]}
        and not in_test_dir
        and not bm.SKIPPED_DIRS & set(parts)
        and not bm.TEST_FILE.search(parts[-1])
    )


def dev_candidates(repo: str, paths: Sequence[str], language: str) -> list[str]:
    ordered = sorted(
        (p for p in paths if candidate_path(p, language)),
        key=lambda p: hashlib.sha256(p.encode()).hexdigest(),
    )
    ids = [f"{repo}:{p}" for p in ordered]
    assigned = splits.assignments(ids)
    return [p for p, i in zip(ordered, ids, strict=True) if assigned[i] == "dev"]


def corpus_inputs(language: str, cache: Path, per_repo: int) -> LanguageInputs:
    """Dev-split verified-corpus rows (and, for X, facts) of one language."""
    manifest = json.loads(ir.MANIFEST.read_text())
    suffix = bm.SUFFIXES[language]
    corpus: dict[str, list[int]] = {m: [] for m in MEASURES}
    records: list[Record] = []
    files = 0
    for repo in manifest["repositories"]:
        if (
            repo["status"] != "verified"
            or MANIFEST_NAME[language] not in repo["languages"]
        ):
            continue
        checkout, sha = cache / repo["name"].replace("/", "__"), repo["pin_sha"]
        if not checkout.is_dir():
            continue
        names = ir.git_out(checkout, "ls-tree", "-r", "--name-only", sha).decode()
        taken = 0
        for path in dev_candidates(repo["name"], names.splitlines(), language):
            if taken >= per_repo:
                break
            blob = ir.git_out(checkout, "show", f"{sha}:{path}")
            if not ir.MIN_BYTES <= len(blob) <= ir.MAX_BYTES:
                continue
            name = f"module{suffix}"
            try:
                rows = bm.raw_measure_sources({name: blob}, language)["functions"]
                facts = extract_facts(blob, language, name)
            except Exception:  # noqa: BLE001, S112 - a file the parser rejects is skipped
                continue
            taken += 1
            files += 1
            for m in MEASURES:
                corpus[m] += br.example_values(rows, m)
            records.append(facts)
    return LanguageInputs(corpus, files, [], [], records)


def agreed_inputs(language: str, corpus: LanguageInputs) -> LanguageInputs:
    """Add the agreed examples (rows for calibrate, facts for the reference line)."""
    records = bd.reference_records("agreed", language)
    root = bd.REFERENCE_ROOT / "agreed"
    examples = []
    for problem in sorted(p for p in root.iterdir() if p.is_dir()):
        directory = problem / language
        if not directory.is_dir():
            continue
        measured = bm.raw_measure_directory(directory, language)["functions"]
        examples.append([{m: row.get(m) for m in MEASURES} for row in measured])
    return LanguageInputs(
        corpus.corpus,
        corpus.corpus_files,
        examples,
        records,
        [*records, *corpus.reference_records],
    )


def load_inputs(cache: Path, per_repo: int) -> dict[str, LanguageInputs]:
    found = {lang: corpus_inputs(lang, cache, per_repo) for lang in LANGUAGES}
    found["python"] = agreed_inputs("python", found["python"])
    return found


# ---- CLI --------------------------------------------------------------------


def check(built: Built, out: Path) -> list[str]:
    problems = []
    # t10 finalization rewrites only states, reasons and `validated`
    if not out.is_file() or bbc.reset_states(out.read_text()) != built.text:
        problems.append(f"{out} differs from the rebuild")
    x_python = built.x_tenths["python"]
    below = [s for s in built.agreed_scores if tenths(s) < x_python]
    if below:
        problems.append(f"agreed Python samples below X={x_python / 10}: {below}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--cache", type=Path, default=USER_CACHE)
    parser.add_argument("--per-repo", type=int, default=PER_REPO)
    args = parser.parse_args(argv)
    built = build(load_inputs(args.cache, args.per_repo))
    if not args.check:
        args.out.write_text(built.text)
        print(f"wrote {args.out} ({len(built.text)} bytes)")
        return 0
    problems = check(built, args.out)
    for problem in problems:
        print(f"check FAIL: {problem}", file=sys.stderr)
    agreed = [round(s, 1) for s in built.agreed_scores]
    status = "ok" if not problems else "FAIL"
    print(f"check: {status} X(tenths)={dict(built.x_tenths)} agreed={agreed}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
