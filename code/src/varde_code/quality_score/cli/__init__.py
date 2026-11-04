"""Command line interface for scoring facts files."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from varde_code.git import run_git

from .. import reference as ref
from .. import vs
from ..breakdown import breakdown
from ..calibration import load_calibration, load_profile
from ..delta import judge
from ..file_advisories import delegation_advisory, fragmentation_advisory
from ..file_facts import exact_facts, facts_for_file, language_of
from ..fix_explain import fixes as ranked_fixes
from ..fix_explain import no_scored_fix_note
from ..refactor_line import limits_of, monolith_advisory, reference_line
from ..scoring import explain, score_scope
from ..user_text import render_text
from ..user_view import user_view

LINE_ONLY_VS = frozenset({"generic", "mine"})


def _first_monolith(
    records: list[dict[str, Any]], calibration: Any
) -> dict[str, Any] | None:
    for record in records:
        language = calibration.languages.get(record.get("language"))
        if language is None:
            continue
        advisory = monolith_advisory(record, limits_of(language.parameters))
        if advisory is not None:
            return advisory
    return None


def _first_advisory(
    records: list[dict[str, Any]], advisory: Callable[[dict[str, Any]], Any]
) -> dict[str, Any] | None:
    return next((found for r in records if (found := advisory(r)) is not None), None)


def _facts(path: str) -> list[dict[str, Any]]:
    records = []
    for line_number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TypeError(f"facts line {line_number} must be a JSON object")
        contract = value.get("contract")
        if contract not in {"facts-1", "facts-2"}:
            raise ValueError(
                f"unsupported facts contract {contract!r} on line {line_number}; "
                "expected facts-1 or facts-2"
            )
        records.append(value)
    return records


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="varde code score",
        description=(
            "Under construction: all languages are report-only; verdicts are advisory."
        ),
    )
    parser.add_argument("--facts", help="facts JSONL (needs --calibration)")
    parser.add_argument(
        "--calibration",
        help="calibration TOML (default: cal-2 from cal-1.toml, with --file)",
    )
    parser.add_argument("--file", help="score one source file of a git repository")
    parser.add_argument(
        "--reference",
        help="with --file: reference JSON path, or 'auto' (stored or built)",
    )
    parser.add_argument(
        "--base", help="with --file: git ref of the same file, for worse-than-before"
    )
    parser.add_argument(
        "--vs",
        choices=vs.VS_NAMES,
        help="with --file: judge against repo (default), generic or mine",
    )
    parser.add_argument("--profile")
    parser.add_argument("--scope")
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="print the user view as JSON, with per-function guidance",
    )
    parser.add_argument(
        "--debug", action="store_true", help="print the raw scorer JSON"
    )
    return parser


def _verdict_fixes(
    records: list[dict[str, Any]], calibration: Any, verdict: dict[str, Any] | None
) -> list[dict[str, Any]] | None:
    """Ranked fixes of the one ``--file`` record, when the verdict has a line."""
    line = None if verdict is None else verdict.get("line")
    if line is None or len(records) != 1:
        return None
    fix_list = ranked_fixes(records[0], calibration, line)
    if verdict and verdict.get("needs_refactor"):
        note = no_scored_fix_note(records[0], calibration, fix_list)
        verdict["message"] = "; ".join(filter(None, [verdict["message"], note]))
    return fix_list


def _repo_root(file: Path) -> Path:
    top = run_git(["rev-parse", "--show-toplevel"], file.parent)
    if top is None:
        raise ValueError(f"{file} is not inside a git repository")
    return Path(top.strip()).resolve()


def _check_options(args: argparse.Namespace) -> None:
    if bool(args.facts) == bool(args.file):
        raise ValueError("give exactly one of --facts and --file")
    if args.facts and not args.calibration:
        raise ValueError("--facts needs --calibration")
    if args.facts and (args.reference or args.base):
        raise ValueError("--reference and --base need --file")
    if args.facts and args.vs:
        raise ValueError("--vs needs --file")
    if args.vs == "repo" and not args.reference:
        args.reference = "auto"
    line_only = args.vs in LINE_ONLY_VS
    if args.reference and line_only:
        raise ValueError(f"--reference is for --vs repo, not --vs {args.vs}")
    if args.base and line_only:
        raise ValueError(f"--base is for --vs repo, not --vs {args.vs}")


def _check_reference_matches(
    reference: ref.Reference, calibration: Any, language: str
) -> None:
    scores = reference.get("scores")
    valid_scores = isinstance(scores, list) and all(
        isinstance(s, (int, float)) and not isinstance(s, bool) for s in scores
    )
    if not valid_scores:
        raise ValueError("reference has no valid 'scores' list of numbers; rebuild it")
    if reference.get("language") != language:
        raise ValueError(
            f"reference is for {reference.get('language')!r}, not {language!r}; "
            "rebuild it"
        )
    if reference.get("calibration_sha256") != calibration.source_sha256:
        raise ValueError(
            f"reference was built with {reference.get('calibration_id')!r}, "
            f"not {calibration.id!r}; rebuild it"
        )


def _line_verdict(
    record: dict[str, Any], reference: vs.Reference
) -> dict[str, Any] | None:
    score = ref.score_of_facts(record, reference.calibration)
    return None if score is None else vs.verdict(reference, score)


def _file_verdict(
    args: argparse.Namespace,
    record: dict[str, Any],
    root: Path,
    rel: str,
    calibration: Any,
) -> dict[str, Any] | None:
    """The delta ``refactor`` field for ``--file``, or None when nothing was asked."""
    if not (args.reference or args.base):
        return None
    now = ref.score_of_facts(record, calibration)
    if now is None:
        return None
    before = None
    if args.base:
        try:
            base_facts = facts_for_file(root, rel, args.base)
        except FileNotFoundError:
            base_facts = None
        if base_facts is not None:
            before = ref.score_of_facts(base_facts, calibration)
    no_before = bool(args.base) and before is None
    scores = None
    if args.reference:
        stored = None if args.reference == "auto" else Path(args.reference)
        reference = ref.load_or_build(root, language_of(rel), stored)
        _check_reference_matches(reference, calibration, language_of(rel))
        scores = reference["scores"]
    verdict = judge(now, before, scores)
    if scores is not None:
        header = vs.repo_header(len(scores))
        verdict = {**header, **verdict}
        if len(scores) >= ref.N_MIN:
            verdict["line"] = reference_line(scores)
        verdict["message"] = vs.with_header(
            header["reference_name"], verdict["message"]
        )
    if no_before:
        note = f"no before for this file at {args.base}"
        verdict["message"] = "; ".join(filter(None, [note, verdict["message"]]))
    return verdict


def _load_records(
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], Any, dict[str, Any] | None]:
    """Facts records, calibration and the optional ``--file`` verdict."""
    if args.facts:
        return _facts(args.facts), load_calibration(args.calibration), None
    file = Path(args.file).resolve()
    root = _repo_root(file)
    rel = file.relative_to(root).as_posix()
    record = exact_facts(file.read_bytes(), language_of(rel), rel)
    calibration = load_calibration(args.calibration or ref.CALIBRATION)
    if args.vs in LINE_ONLY_VS:
        reference = vs.resolve(args.vs, language_of(rel), calibration)
        return [record], reference.calibration, _line_verdict(record, reference)
    return [record], calibration, _file_verdict(args, record, root, rel, calibration)


def run(argv: list[str], io: Any = None) -> int:
    stdout: TextIO = getattr(io, "stdout", sys.stdout)
    stderr: TextIO = getattr(io, "stderr", sys.stderr)
    try:
        args = _parser().parse_args(argv[1:])
        _check_options(args)
        records, calibration, verdict = _load_records(args)
        if args.scope:
            scope = Path(args.scope).as_posix().rstrip("/")
            records = [
                r
                for r in records
                if r.get("path") == scope
                or str(r.get("path", "")).startswith(scope + "/")
            ]
        records.sort(
            key=lambda record: (
                str(record.get("path", "")),
                min(
                    (
                        function.get("line", 0)
                        for function in record.get("functions", [])
                    ),
                    default=0,
                ),
                max(
                    (
                        function.get("end_line", function.get("line", 0))
                        for function in record.get("functions", [])
                    ),
                    default=0,
                ),
            )
        )
        profile = load_profile(args.profile, calibration) if args.profile else None
        scored = score_scope(records, calibration, profile)
        payload = explain(scored)
        payload["calibration"] = calibration.output_label
        payload["breakdown"] = breakdown(scored, calibration, records)
        payload["files"] = [
            {
                **explain(score_scope([record], calibration, profile))["files"][0],
                "breakdown": breakdown(
                    score_scope([record], calibration, profile), calibration
                ),
            }
            for record in records
        ]
        if args.debug:
            print(json.dumps(payload, sort_keys=True), file=stdout)
            return 0
        view = user_view(
            payload,
            payload["breakdown"],
            refactor=verdict,
            fixes=_verdict_fixes(records, calibration, verdict),
            monolith=_first_monolith(records, calibration),
            file_advisories={
                "delegation": _first_advisory(records, delegation_advisory),
                "fragmentation": _first_advisory(records, fragmentation_advisory),
            },
        )
        if args.json_output:
            print(json.dumps(view, sort_keys=True), file=stdout)
        else:
            stdout.write(render_text(view))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"code score: {exc}", file=stderr)
        return 2
    else:
        return 0
