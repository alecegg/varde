"""Report and validation command handlers."""

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Sequence
from pathlib import Path

from varde_dev.calibrate.reports.config import DEFAULT_OVER_SPLIT_CATEGORY
from varde_dev.calibrate.reports.dataset import read_dataset_files
from varde_dev.calibrate.reports.tables import build_report
from varde_dev.calibrate.reports.validation import read_scores, validation_record


def main(command: str, argv: Sequence[str] | None = None) -> int:
    if command == "report":
        return _run_report(argv)
    if command == "validate":
        return _run_validate(argv)
    raise ValueError(f"unknown report command: {command}")


def _run_report(argv: Sequence[str] | None) -> int:
    parser = argparse.ArgumentParser(prog="python -m varde_dev.calibrate report")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--by", default="category,language,lens")
    parser.add_argument("--over-split-category", default=DEFAULT_OVER_SPLIT_CATEGORY)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        dataset = read_dataset_files(args.dataset)
        result = build_report(
            dataset["labels"],
            dataset["units"],
            dataset["items"],
            by=tuple(part.strip() for part in args.by.split(",") if part.strip()),
            over_split_category=args.over_split_category,
        )
        _print(result, args.json)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return _error("report", error)
    else:
        return 0


def _run_validate(argv: Sequence[str] | None) -> int:
    parser = argparse.ArgumentParser(prog="python -m varde_dev.calibrate validate")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--language", required=True)
    parser.add_argument("--rater", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--scores", type=Path)
    source.add_argument("--score-cmd")
    parser.add_argument("--category-b", default="b")
    parser.add_argument("--held-out-splits", default="test,held-out")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        dataset = read_dataset_files(args.dataset)
        scores = _read_score_input(args)
        record_path = args.dataset / "validation" / f"{args.language}.toml"
        previous = (
            tomllib.loads(record_path.read_text(encoding="utf-8"))
            if record_path.is_file()
            else None
        )
        record = validation_record(
            dataset=dataset,
            language=args.language,
            rater_id=args.rater,
            scores=scores,
            previous=previous,
            options={
                "category_b": args.category_b,
                "held_out_splits": tuple(
                    part.strip()
                    for part in args.held_out_splits.split(",")
                    if part.strip()
                ),
            },
        )
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(_record_toml(record), encoding="utf-8")
        _print(record, args.json)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return _error("validate", error)
    else:
        return 0


def _read_score_input(args: argparse.Namespace) -> list[dict[str, object]]:
    if args.scores is not None:
        return read_scores(args.scores)
    command = shlex.split(args.score_cmd)
    if not command:
        raise ValueError("--score-cmd must contain a command")
    completed = subprocess.run(  # noqa: S603 - Runs the configured local report command with explicit arguments.
        [*command, str(args.dataset)], check=False, capture_output=True, text=True
    )
    if completed.returncode:
        raise ValueError(f"score command failed: {completed.stderr.strip()}")
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".jsonl"
    ) as output:
        output.write(completed.stdout)
        output.flush()
        return read_scores(output.name)


def _print(result: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return
    for section, value in result.items():
        print(f"{section}: {json.dumps(value, sort_keys=True, ensure_ascii=False)}")


def _record_toml(record: dict[str, object]) -> str:
    lines = []
    sections = {"validated_against", "thresholds", "agreement"}
    for key, value in record.items():
        if key in sections or value is None:
            continue
        lines.append(f"{key} = {_toml_value(value)}")
    for section in ("validated_against", "thresholds", "agreement"):
        lines.append("")
        lines.append(f"[{section}]")
        values = record[section]
        for key, value in values.items():
            if value is not None:
                lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"


def _toml_value(value: object) -> str:
    if isinstance(value, (str, list, bool, int, float)):
        return json.dumps(value, ensure_ascii=False)
    raise TypeError(f"unsupported validation TOML value: {type(value).__name__}")


def _error(command: str, error: Exception) -> int:
    print(f"calibrate {command}: {error}", file=sys.stderr)
    return 1
