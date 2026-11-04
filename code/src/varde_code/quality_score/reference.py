"""Reference scores from a repository's own source files.

The reference is the sorted list of per-file scores of the repo's own files at
HEAD (scored with the existing scorer and calibration cal-2), with provenance.
It is plain data. It says where a file stands among its repo's own files and
makes no absolute claim about code quality.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from varde_code.quality_score.breakdown import breakdown
from varde_code.quality_score.calibration import (
    Calibration,
    load_calibration,
    shipped_calibration_path,
)
from varde_code.quality_score.file_facts import (
    facts_for_file,
    head_commit,
    list_files,
)
from varde_code.quality_score.scoring import explain, score_scope
from varde_code.quality_score.user_view import user_view
from varde_code.rules.scan_output import is_generated_path

CALIBRATION = shipped_calibration_path()
DEFAULT_CAP = 200
N_MIN = 20  # p10 sd over random samples: n=10 23.0, n=20 11.9, n=50 6.6
LOW_CONFIDENCE_N = 50
BUILT_BY_COMMAND = "command"
BUILT_AUTO = "auto"
TEST_DIRS = frozenset({"test", "tests", "__tests__", "spec", "specs"})
BENCHMARK_DIRS = frozenset({"bench", "benches", "benchmark", "benchmarks"})
TEST_SUFFIXES = (
    ".test.ts",
    ".spec.ts",
    ".test.tsx",
    ".spec.tsx",
    "Tests.cs",
    "Test.cs",
)

Reference = dict[str, Any]


class ReferenceError(ValueError):
    """The repo has no scorable source files to build a reference from."""


def is_test_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    name = parts[-1] if parts else ""
    return (
        any(part in TEST_DIRS for part in parts[:-1])
        or name.startswith("test_")
        or name.endswith(("_test.py", *TEST_SUFFIXES))
        or name == "conftest.py"
    )


def is_benchmark_path(path: str) -> bool:
    """Whether a directory of the path is a benchmark harness (not shipped code)."""
    return any(part in BENCHMARK_DIRS for part in PurePosixPath(path).parts[:-1])


def is_reference_path(path: str) -> bool:
    """Whether the path is shipped code: not a test, benchmark or generated file."""
    return not (
        is_test_path(path) or is_benchmark_path(path) or is_generated_path(path)
    )


def eligible_paths(paths: list[str], cap: int) -> list[str]:
    """At most ``cap`` of the sorted shipped-code paths, evenly strided.

    A stride over the sorted list keeps late directories in the sample; the
    first ``cap`` paths alone would skew the reference to early directories.
    """
    kept = sorted(p for p in paths if is_reference_path(p))
    if len(kept) <= cap:
        return kept
    return [kept[i * len(kept) // cap] for i in range(cap)]


def confidence(n: int) -> str:
    """``insufficient`` below N_MIN, ``low`` below LOW_CONFIDENCE_N, else ``ok``."""
    if n < N_MIN:
        return "insufficient"
    return "low" if n < LOW_CONFIDENCE_N else "ok"


def score_of_facts(facts: dict[str, Any], calibration: Calibration) -> float | None:
    """The 0-100 score of one file's facts, or None when it has no scorable code."""
    scored = score_scope([facts], calibration)
    view = user_view(explain(scored), breakdown(scored, calibration))
    return view["score"]


def make_reference(
    scores: list[float],
    *,
    language: str,
    calibration: Calibration,
    commit: str,
    built: str,
) -> Reference:
    """The plain-data reference; scores are sorted so the JSON is deterministic."""
    ordered = sorted(scores)
    return {
        "language": language,
        "scores": ordered,
        "n": len(ordered),
        "calibration_id": calibration.id,
        "calibration_sha256": calibration.source_sha256,
        "commit": commit,
        "built": built,
    }


def build(
    root: Path,
    language: str,
    cap: int = DEFAULT_CAP,
    *,
    built: str = BUILT_BY_COMMAND,
) -> Reference:
    """Score the repo's own files at HEAD (sorted path order, at most ``cap``)."""
    calibration = load_calibration(CALIBRATION)
    scores = []
    for path in eligible_paths(list_files(root, language), cap):
        score = score_of_facts(facts_for_file(root, path), calibration)
        if score is not None:
            scores.append(score)
    if not scores:
        raise ReferenceError(f"no scorable {language} source files in {root} at HEAD")
    return make_reference(
        scores,
        language=language,
        calibration=calibration,
        commit=head_commit(root),
        built=built,
    )


def default_path(root: Path, language: str) -> Path:
    return root / ".varde" / "quality" / f"reference-{language}.json"


def write(reference: Reference, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(reference, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def read(path: Path) -> Reference:
    return json.loads(path.read_text(encoding="utf-8"))


def load_or_build(
    root: Path, language: str, path: Path | None = None, cap: int = DEFAULT_CAP
) -> Reference:
    """The stored reference, else one built in memory and marked ``auto``."""
    stored = path or default_path(root, language)
    if stored.is_file():
        return read(stored)
    return build(root, language, cap, built=BUILT_AUTO)
