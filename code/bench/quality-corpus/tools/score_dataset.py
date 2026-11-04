"""Score every panel dataset item with a calibration (read-only; no model calls).

Writes deterministic `scores.jsonl` (sorted by item id, fixed-point integers,
no timestamps), `unscored.jsonl` (items that could not be scored, with the
reason) and `run.json` (varde commit and calibration identity) to --out.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
CODE_SRC = ROOT / "code/src"
if str(CODE_SRC) not in sys.path:
    sys.path.insert(0, str(CODE_SRC))

from varde_code.quality_pass.facts import extract_facts  # noqa: E402, RUF100
from varde_code.quality_score.calibration import Calibration, load_calibration  # noqa: E402, RUF100
from varde_code.quality_score.scoring import score_scope  # noqa: E402, RUF100

CALIBRATION_DIR = CODE_SRC / "varde_code/quality_score/calibration"
PLAN_DIR_ENV = "VARDE_CALIBRATION_PLAN_DIR"
DEFAULT_PLAN_DIR = Path(
    "/Users/alec/source/agent-memory/projects/varde-py/working/plans"
    "/2026-10-30-vqs-v1-poc/calibration"
)
DATASET_SUBPATH = Path("panel/notes/panel-1/dataset")
DEFAULT_SPLITS = "dev,regression"
SUFFIXES = {
    "python": ".py",
    "typescript": ".ts",
    "csharp": ".cs",
    "java": ".java",
    "go": ".go",
    "rust": ".rs",
    "cpp": ".cpp",
}
OUTPUT_FILES = ("scores.jsonl", "unscored.jsonl")


def plan_dir() -> Path:
    return Path(os.environ.get(PLAN_DIR_ENV, DEFAULT_PLAN_DIR))


def default_dataset() -> Path:
    return plan_dir().parent / DATASET_SUBPATH


def default_calibration() -> Path:
    """`cal-1.toml` once it exists, else the placeholder (until t12)."""
    candidate = CALIBRATION_DIR / "cal-1.toml"
    return candidate if candidate.is_file() else CALIBRATION_DIR / "placeholder.toml"


def read_items(dataset: Path, splits: frozenset[str]) -> list[dict[str, Any]]:
    """Items of the named splits only; other splits are never parsed further."""
    items = []
    with (dataset / "items.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("record_type") == "items" or row.get("split") not in splits:
                continue
            items.append(row)
    return sorted(items, key=lambda row: row["id"])


def item_path(item: dict[str, Any]) -> str:
    suffix = SUFFIXES.get(item["language"], "")
    return "dataset/" + item["id"].replace(":", "_") + suffix


def unscored(item: dict[str, Any], reason: str) -> dict[str, Any]:
    return {"id": item["id"], "language": item["language"], "reason": reason}


def score_item(
    item: dict[str, Any], calibration: Calibration
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (score row, None) or (None, unscored row)."""
    language = item["language"]
    if language not in calibration.languages or language not in SUFFIXES:
        return None, unscored(item, f"unsupported language {language}")
    try:
        facts = extract_facts(item["text"], language, item_path(item))
        scope = score_scope([facts], calibration)
    except (ValueError, RuntimeError, KeyError, TypeError) as exc:
        return None, unscored(item, f"parse or score failed: {type(exc).__name__}")
    file = scope.files[0] if scope.files else None
    if file is None or file.excluded or file.not_applicable or file.tokens <= 0:
        reason = file.excluded if file and file.excluded else "no scorable tokens"
        return None, unscored(item, f"not scored: {reason}")
    return {
        "id": item["id"],
        "language": language,
        "split": item["split"],
        "tokens": file.tokens,
        "debt": file.debt,
        "density": file.density,
        "score": file.score,
        "gate_score": file.gate_score,
    }, None


def score_dataset(
    items: list[dict[str, Any]], calibration: Calibration
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scores: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in items:
        score, reason = score_item(item, calibration)
        if score is not None:
            scores.append(score)
        if reason is not None:
            skipped.append(reason)
    return scores, skipped


def jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def varde_commit() -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(  # noqa: S603 - fixed git argv.
            ["git", "-C", str(ROOT), *args],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()

    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--short"))}


def write_outputs(
    out: Path,
    scores: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    calibration: Calibration,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "scores.jsonl").write_text(jsonl(scores), encoding="utf-8")
    (out / "unscored.jsonl").write_text(jsonl(skipped), encoding="utf-8")
    run = {
        **varde_commit(),
        "calibration_id": calibration.id,
        "calibration_sha256": calibration.source_sha256,
        "scored": len(scores),
        "unscored": len(skipped),
    }
    (out / "run.json").write_text(
        json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def differing_files(first: Path, second: Path) -> list[str]:
    return [
        name
        for name in OUTPUT_FILES
        if (first / name).read_bytes() != (second / name).read_bytes()
    ]


def check_determinism(args: argparse.Namespace, first: Path) -> int:
    """Re-score in a fresh process (warm grammar cache) and compare bytes."""
    with tempfile.TemporaryDirectory() as tmp:
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--dataset",
            str(args.dataset),
            "--calibration",
            str(args.calibration),
            "--splits",
            args.splits,
            "--out",
            tmp,
        ]
        result = subprocess.run(command, check=False)  # noqa: S603
        if result.returncode != 0:
            print("FAIL: second scoring run exited non-zero", file=sys.stderr)
            return 1
        differing = differing_files(first, Path(tmp))
    for name in differing:
        print(f"FAIL: {name} differs between runs")
    if not differing:
        print("determinism: scores.jsonl and unscored.jsonl are byte-identical")
    return 1 if differing else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=default_dataset())
    parser.add_argument("--calibration", type=Path, default=default_calibration())
    parser.add_argument("--splits", default=DEFAULT_SPLITS)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check-determinism", action="store_true")
    args = parser.parse_args()
    out = args.out or args.dataset.parent / "scores"
    calibration = load_calibration(args.calibration)
    splits = frozenset(item.strip() for item in args.splits.split(",") if item.strip())
    scores, skipped = score_dataset(read_items(args.dataset, splits), calibration)
    write_outputs(out, scores, skipped, calibration)
    print(
        f"scored {len(scores)} items, unscored {len(skipped)}; "
        f"calibration {calibration.id} sha256 {calibration.source_sha256}; "
        f"output {out}"
    )
    for row in skipped:
        print(f"unscored: {row['id']} ({row['language']}): {row['reason']}")
    return check_determinism(args, out) if args.check_determinism else 0


if __name__ == "__main__":
    raise SystemExit(main())
