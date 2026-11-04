"""Per-file verdict and fix list for ``varde scan`` (a report field, not a finding).

The verdict has no rule id, no severity and no effect on the exit code. It is
computed only when quality is on and the input names ``vs``, ``changedSince`` or
``verdict: true``. Shown files are the changed ones (``changedSince``), else all
parsed non-test files. Their records get ``delegates`` from ``exact_facts`` so the
wrapper measure counts; the stored facts and their cache keys are not touched.
The shown score is the graph-enriched ``score_scope([record])`` score (0-100,
tenths), so its basis is ``graph``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from varde_code.quality_score import fix_explain, score_scope, vs
from varde_code.quality_score.calibration import Calibration
from varde_code.quality_score.delta import judge
from varde_code.quality_score.file_facts import exact_facts, language_of
from varde_code.quality_score.guidance import short_name
from varde_code.quality_score.refactor_line import reference_line
from varde_code.quality_score.reference import (
    DEFAULT_CAP,
    N_MIN,
    eligible_paths,
    is_reference_path,
    score_of_facts,
)
from varde_code.quality_score.scoring.scoring import STRUCTURE
from varde_code.scan import changed_since
from varde_code.scan.quality_scores import (
    calibrated_records,
    is_unparsed,
    merge_measures,
)

KEY = "quality_verdict"
NOTE_KEY = "quality_verdict_note"
SKIPPED_NOTE = "no quality verdict: quality is off (skipQuality or quality disabled)"
BASIS = "graph"
DEFAULT_VS = "repo"


def requested(scan_input: Mapping[str, Any]) -> bool:
    """Whether the input asks for verdicts (the caller checks quality is on)."""
    return bool(
        scan_input.get("vs")
        or scan_input.get("changedSince")
        or scan_input.get("verdict") is True
    )


def _key(function: Mapping[str, Any]) -> tuple[Any, str]:
    return function.get("line"), short_name(str(function.get("id", "")))


def _delegates_by_key(exact: Mapping[str, Any]) -> dict[tuple[Any, str], Any]:
    return {
        _key(fn): {k: fn[k] for k in ("delegates", "hook") if k in fn}
        for fn in exact.get("functions", ())
        if "delegates" in fn
    }


def asked_by_name(scan_input: Mapping[str, Any]) -> bool:
    """Whether the input asked for a verdict itself (``vs`` or ``verdict: true``)."""
    return bool(scan_input.get("vs") or scan_input.get("verdict") is True)


def overlay_delegates(
    record: dict[str, Any], exact: Mapping[str, Any]
) -> dict[str, Any]:
    """``record`` with ``delegates`` and ``hook`` from ``exact``, by (line, name)."""
    by_key = _delegates_by_key(exact)
    functions = [
        {**fn, **by_key[_key(fn)]} if _key(fn) in by_key else fn
        for fn in record["functions"]
    ]
    return {**record, "functions": functions}


def unmatched_count(record: Mapping[str, Any], exact: Mapping[str, Any]) -> int:
    """Functions of ``record`` with no (line, name) counterpart in ``exact``."""
    known = {_key(fn) for fn in exact.get("functions", ())}
    return sum(1 for fn in record["functions"] if _key(fn) not in known)


def shown_paths(
    paths: Iterable[str], changed: frozenset[str] | None, limit_to_changed: bool
) -> list[str]:
    """Sorted reference-eligible paths: the changed ones when limited, else all."""
    eligible = [path for path in paths if is_reference_path(path)]
    if limit_to_changed:
        eligible = [path for path in eligible if path in (changed or frozenset())]
    return sorted(eligible)


def repo_verdict(
    path: str, score: float, scores_by_path: Mapping[str, float]
) -> dict[str, Any]:
    """The ``repo`` verdict of one file against the others' scores (it is left out)."""
    others = [value for other, value in scores_by_path.items() if other != path]
    result = judge(score, None, others)
    header = vs.repo_header(len(others), BASIS)
    verdict = {**header, **result, "score": score}
    if len(others) >= N_MIN:
        verdict["line"] = reference_line(others)
    verdict["message"] = vs.with_header(
        header["reference_name"], result["message"], BASIS
    )
    return verdict


def line_of(verdict: Mapping[str, Any]) -> float | None:
    return verdict.get("line")


def fixes_for(
    record: dict[str, Any], calibration: Calibration, verdict: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """The fix list of a file the verdict calls worth refactoring, else empty."""
    line = line_of(verdict)
    if line is None or not verdict.get("needs_refactor"):
        return []
    return fix_explain.fixes(record, calibration, line)


def _exact(root: Path, record: Mapping[str, Any]) -> dict[str, Any] | None:
    path = record["path"]
    try:
        return exact_facts((root / path).read_bytes(), language_of(path), path)
    except OSError, ValueError:
        return None


Overlaid = dict[str, tuple[dict[str, Any], int]]


def _overlaid(
    root: Path, record: dict[str, Any], cache: Overlaid
) -> tuple[dict[str, Any], int]:
    """The record with exact ``delegates`` and its unmatched-function count."""
    path = record["path"]
    if path not in cache:
        exact = _exact(root, record)
        cache[path] = (
            (record, 0)
            if exact is None
            else (overlay_delegates(record, exact), unmatched_count(record, exact))
        )
    return cache[path]


def _reference_scores(
    root: Path,
    records: Iterable[dict[str, Any]],
    calibration: Calibration,
    cache: Overlaid,
) -> dict[str, dict[str, float]]:
    """``{language: {path: score}}`` of the strided reference sample, sd overlaid.

    At most ``DEFAULT_CAP`` files per language are read, as for the ``repo``
    reference of ``varde score``, so the cost does not grow with the repo.
    """
    by_path: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("language") in calibration.languages:
            by_path[record["path"]] = record
    paths_by_language: dict[str, list[str]] = {}
    for path, record in by_path.items():
        paths_by_language.setdefault(record["language"], []).append(path)
    result: dict[str, dict[str, float]] = {}
    for language, paths in paths_by_language.items():
        for path in eligible_paths(paths, DEFAULT_CAP):
            merged, _ = _overlaid(root, by_path[path], cache)
            score = score_of_facts(merged, calibration)
            if score is not None:
                result.setdefault(language, {})[path] = score
    return result


def graph_note(components: Mapping[str, int]) -> str:
    """Says so when call-graph measures are the largest loss (file-only omits them)."""
    structure = sum(components.get(name, 0) for name in STRUCTURE)
    others = max((v for k, v in components.items() if k not in STRUCTURE), default=0)
    if not structure or structure < others:
        return ""
    return (
        "most of the loss is call-graph structure (depth, fan-out, tree size), which "
        "`varde score --file` does not measure, so that file-only score is higher"
    )


def _file_entry(
    record: dict[str, Any],
    reference: vs.Reference | None,
    calibration: Calibration,
    scores: Mapping[str, float],
    unmatched: int = 0,
) -> dict[str, Any]:
    path = record["path"]
    use = calibration if reference is None else reference.calibration
    score = score_of_facts(record, use)
    if score is None:
        return {"path": path, "language": record["language"], "score": None}
    if reference is None:
        verdict = repo_verdict(path, score, scores)
    else:
        verdict = vs.verdict(reference, score, BASIS)
    fix_list = fixes_for(record, use, verdict)
    entry = {
        "path": path,
        "language": record["language"],
        "score": score,
        "verdict": verdict,
        "fixes": fix_list,
    }
    if verdict.get("needs_refactor"):
        note = fix_explain.no_scored_fix_note(record, use, fix_list)
        components = score_scope([record], use).files[0].components
        notes = [note, graph_note(components)]
        verdict["message"] = "; ".join(filter(None, [verdict["message"], *notes]))
        if note:
            entry["fix_note"] = note
    if unmatched:
        entry["unmatched_functions"] = unmatched
        verdict["message"] += (
            f" ({unmatched} functions had no exact wrapper facts, so the wrapper "
            "measure may be incomplete)"
        )
    return entry


def _reference_summary(
    language: str, reference: vs.Reference | None, count: int
) -> dict[str, Any]:
    if reference is None:
        return {"language": language, "reference_name": f"repo (n={count})", "n": count}
    key = "n" if reference.name == "repo" else "k"
    return {
        "language": language,
        "reference_name": reference.label,
        key: reference.n_or_k,
    }


def _references(
    vs_name: str, languages: Iterable[str], calibration: Calibration
) -> dict[str, vs.Reference | None]:
    """One reference per language; ``repo`` has none (its scores are the list)."""
    if vs_name == DEFAULT_VS:
        return dict.fromkeys(languages)
    return {name: vs.resolve(vs_name, name, calibration) for name in languages}


def build(
    root: Path, scan_input: Mapping[str, Any], calibration: Calibration
) -> dict[str, Any]:
    """The ``quality_verdict`` report field for the shown files of ``root``."""
    vs_name = scan_input.get("vs") or DEFAULT_VS
    ref = scan_input.get("changedSince")
    changed = changed_since.read_changed_paths(root, ref) if ref else None
    parsed = [r for r in merge_measures(root) if not is_unparsed(r)]
    records = calibrated_records(parsed, calibration)
    wanted = set(
        shown_paths((r["path"] for r in records), changed, limit_to_changed=bool(ref))
    )
    shown = [
        r
        for r in sorted(records, key=lambda r: r["path"])
        if r["path"] in wanted and r.get("language") in calibration.languages
    ]
    languages = sorted({r["language"] for r in shown})
    references = _references(vs_name, languages, calibration)
    cache: Overlaid = {}
    by_language = (
        _reference_scores(root, records, calibration, cache)
        if vs_name == DEFAULT_VS
        else {}
    )
    files = []
    for record in shown:
        language = record["language"]
        merged, unmatched = _overlaid(root, record, cache)
        scores = by_language.get(language, {})
        files.append(
            _file_entry(merged, references[language], calibration, scores, unmatched)
        )
    return {
        "vs": vs_name,
        "basis": BASIS,
        "references": [
            _reference_summary(name, references[name], len(by_language.get(name, {})))
            for name in languages
        ],
        "files": files,
    }
