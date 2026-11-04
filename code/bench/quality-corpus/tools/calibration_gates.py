"""Per-language readiness report for the calibration plan (read-only).

Reads the sibling panel and resolver plans and the tuning check, and writes
`--out` (markdown, one row per language). Exits 0 whenever it can report;
`--require panel,resolver,tuning --languages L` exits 1 when a named input is
not ready. It never edits sibling plan files.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
TOOLS = Path(__file__).resolve().parent
CODE_SRC = ROOT / "code/src"
for _path in (CODE_SRC, TOOLS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from tune_samples import SAMPLES_PATH  # noqa: E402, RUF100
from varde_code.quality_score.samples import load_sample  # noqa: E402, RUF100

DEFAULT_LANGUAGES = "python,typescript,csharp"
INPUTS = ("panel", "resolver", "tuning")
LABEL_SPLITS = ("dev", "regression")
NOTE_LIMIT = 200


@dataclass(frozen=True)
class Status:
    ready: bool
    detail: str


# ---- panel ---------------------------------------------------------------


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [row for row in rows if "record_type" not in row]


def item_index(dataset: Path) -> dict[str, tuple[str, str]]:
    """Item id -> (language, split) for the label-bearing splits."""
    return {
        row["id"]: (row["language"], row["split"])
        for row in read_jsonl(dataset / "items.jsonl")
        if row.get("split") in LABEL_SPLITS
    }


def labelled_units(
    dataset: Path, index: dict[str, tuple[str, str]]
) -> dict[tuple[str, str], set[str]]:
    """(language, split) -> unit ids that carry at least one label."""
    found: dict[tuple[str, str], set[str]] = {}
    for batch in sorted((dataset / "labels").glob("*.jsonl")):
        for label in read_jsonl(batch):
            key = index.get(str(label.get("a_item_id")))
            if key is not None:
                found.setdefault(key, set()).add(str(label.get("unit_id")))
    return found


def ledger_check(ledger: Path) -> tuple[bool, str]:
    """Run the panel ledger check; an unavailable command counts as not passing."""
    if not ledger.is_file():
        return False, "ledger missing"
    result = subprocess.run(  # noqa: S603 - fixed argv.
        [
            sys.executable,
            "-m",
            "varde_dev.calibrate",
            "panel-chunk",
            "--check-ledger",
            str(ledger),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0, f"ledger check exit {result.returncode}"


def panel_status(
    panel_dir: Path, language: str, ledger_result: tuple[bool, str]
) -> Status:
    base = panel_dir / "notes/panel-1"
    dataset = base / "dataset"
    problems = []
    if not (base / "handoff.md").is_file():
        problems.append("handoff.md missing")
    index = item_index(dataset)
    splits = sorted({split for lang, split in index.values() if lang == language})
    labelled = labelled_units(dataset, index)
    counts = []
    for split in splits:
        count = len(labelled.get((language, split), set()))
        counts.append(f"{split} {count} labelled")
        if count == 0:
            problems.append(f"no {split} labels")
    if not splits:
        problems.append("no dataset items")
    if not ledger_result[0]:
        problems.append(ledger_result[1])
    detail = "; ".join(problems + counts) or "ready"
    return Status(not problems, detail)


# ---- resolver ------------------------------------------------------------


def verdict_passes(text: str, language: str) -> bool:
    """PASS on a line naming the language, else a whole-file PASS; FAIL blocks."""
    named = [line for line in text.splitlines() if language in line.lower()]
    scope = "\n".join(named) if named else text
    return bool(re.search(r"\bPASS\b", scope)) and not re.search(r"\bFAIL\b", scope)


def recorded_numbers(after: Path) -> str:
    """Last table row of the language's after-note (the recorded P/R), else a hint."""
    if not after.is_file():
        return f"no {after.name}"
    rows = [
        line
        for line in after.read_text(encoding="utf-8").splitlines()
        if line.startswith("|") and "---" not in line
    ]
    return (
        re.sub(r"\s+", " ", rows[-1]).strip() if rows else f"no table in {after.name}"
    )


def needs_new_facts_note(after: Path) -> str:
    if not after.is_file():
        return ""
    for line in after.read_text(encoding="utf-8").splitlines():
        if "needs-new-facts" in line:
            return "needs-new-facts: " + line.strip()[:NOTE_LIMIT]
    return ""


def resolver_status(resolver_dir: Path, language: str) -> Status:
    verdict = resolver_dir / "notes/dev-final/verdict.md"
    if verdict.is_file() and verdict_passes(verdict.read_text("utf-8"), language):
        return Status(True, "dev-final verdict PASS")
    after = resolver_dir / f"notes/gaps/{language}-after.md"
    parts = ["no PASS verdict", recorded_numbers(after), needs_new_facts_note(after)]
    return Status(False, "; ".join(part for part in parts if part))


# ---- tuning --------------------------------------------------------------


def run_tuning_check(languages: str) -> dict[str, Any] | None:
    """Run `tune_samples.py --check --json`; None when it produced no report."""
    result = subprocess.run(  # noqa: S603 - fixed argv.
        [
            sys.executable,
            str(TOOLS / "tune_samples.py"),
            "--languages",
            languages,
            "--check",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    report["exit_code"] = result.returncode
    return report


def sample_languages() -> dict[str, str]:
    return {
        path.name: load_sample(path.name, package_root=SAMPLES_PATH).language
        for path in sorted(SAMPLES_PATH.iterdir())
        if (path / "sample.toml").is_file()
    }


def failing_by_language(
    report: dict[str, Any], languages_of: dict[str, str]
) -> dict[str, list[str]]:
    failing: dict[str, list[str]] = {}
    for sample in report.get("samples", []):
        for item in sample["constraints"]:
            if item["margin"] < 0:
                language = languages_of.get(sample["id"], "?")
                failing.setdefault(language, []).append(
                    f"in-sample {sample['id']} {item['challenger']} {item['margin']:+}"
                )
    for fold in report.get("loo", []):
        for item in fold["margins"]:
            if item["margin"] < 0:
                language = languages_of.get(fold["held_out"], "?")
                failing.setdefault(language, []).append(
                    f"loo {fold['held_out']} {item['challenger']} {item['margin']:+}"
                )
    return failing


def tuning_status(
    report: dict[str, Any] | None,
    language: str,
    languages_of: dict[str, str],
) -> Status:
    if report is None:
        return Status(False, "tuning check not run or produced no report")
    scored = {sample["id"] for sample in report.get("samples", [])}
    samples = sorted(item for item in scored if languages_of.get(item) == language)
    failing = failing_by_language(report, languages_of).get(language, [])
    if not samples:
        return Status(False, "no seeded samples for this language")
    if failing:
        return Status(False, f"{len(samples)} samples; negative: " + ", ".join(failing))
    return Status(True, f"{len(samples)} samples; all margins >= 0")


# ---- report --------------------------------------------------------------


def unmet_inputs(
    statuses: dict[str, dict[str, Status]], required: list[str], languages: list[str]
) -> list[str]:
    return [
        f"{language}: {name} not ready ({statuses[language][name].detail})"
        for language in languages
        for name in required
        if not statuses[language][name].ready
    ]


def render(
    statuses: dict[str, dict[str, Status]], commit: str, tuning_exit: int | None
) -> str:
    cell = {True: "ready", False: "NOT READY"}
    lines = [
        "# Calibration readiness (gates)",
        "",
        f"varde commit: {commit}",
        "tuning check: "
        + (
            "not run"
            if tuning_exit is None
            else f"tune_samples --check exit {tuning_exit}"
        ),
        "",
        "| language | panel labels | resolver verdict | tuning check |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {language} | " + " | ".join(cell[row[name].ready] for name in INPUTS) + " |"
        for language, row in statuses.items()
    )
    for language, row in statuses.items():
        lines.extend(["", f"## {language}"])
        lines.extend(f"- {name}: {row[name].detail}" for name in INPUTS)
    return "\n".join(lines) + "\n"


def varde_commit() -> str:
    result = subprocess.run(  # noqa: S603 - fixed argv.
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "unknown"


def collect(
    plan_dir: Path,
    languages: list[str],
    tuning_report: dict[str, Any] | None,
    languages_of: dict[str, str],
    ledger_result: tuple[bool, str],
) -> dict[str, dict[str, Status]]:
    panel_dir, resolver_dir = plan_dir.parent / "panel", plan_dir.parent / "resolver"
    return {
        language: {
            "panel": panel_status(panel_dir, language, ledger_result),
            "resolver": resolver_status(resolver_dir, language),
            "tuning": tuning_status(tuning_report, language, languages_of),
        }
        for language in languages
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--languages", default=DEFAULT_LANGUAGES)
    parser.add_argument("--require", default="", help="comma-separated inputs")
    parser.add_argument(
        "--skip-tuning", action="store_true", help="do not run tune_samples --check"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    languages = [item.strip() for item in args.languages.split(",") if item.strip()]
    required = [item.strip() for item in args.require.split(",") if item.strip()]
    unknown = [name for name in required if name not in INPUTS]
    if unknown:
        print(f"error: unknown --require input {unknown}", file=sys.stderr)
        return 2
    ledger = args.plan_dir.parent / "panel/notes/panel-1/usage-ledger.jsonl"
    report = None if args.skip_tuning else run_tuning_check(args.languages)
    statuses = collect(
        args.plan_dir,
        languages,
        report,
        sample_languages(),
        ledger_check(ledger),
    )
    tuning_exit = None if report is None else report.get("exit_code")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(statuses, varde_commit(), tuning_exit), encoding="utf-8")
    unmet = unmet_inputs(statuses, required, languages)
    for line in unmet:
        print(f"NOT READY: {line}")
    print(f"wrote {args.out}")
    return 1 if unmet else 0


if __name__ == "__main__":
    raise SystemExit(main())
