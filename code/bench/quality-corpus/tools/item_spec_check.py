"""Command line interface for category (b) item specification checks.

Exit codes: ``0`` for a clean print run, ``1`` when ``--check`` finds
violations, and ``2`` for a usage error or an unusable source (syntax error or
missing grammar). Errors are printed as one structured JSON line, never a
traceback.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from item_spec_extract import SourceSyntaxError
from item_spec_languages import EXTENSIONS
from item_spec_rules import check_item


def item_directories(root: Path) -> list[Path]:
    if any(root.glob("sensible.*")):
        return [root]
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_dir() and any(path.glob("sensible.*"))
    )


def select_language(item: Path, requested: str | None) -> str | None:
    if requested:
        return requested
    return next(
        (
            name
            for name, extension in EXTENSIONS.items()
            if (item / f"sensible{extension}").exists()
        ),
        None,
    )


def _error_line(kind: str, value: str, limit: str) -> str:
    return json.dumps(
        {"kind": kind, "version": "", "function": "", "value": value, "limit": limit},
        sort_keys=True,
    )


def _run(directories: list[Path], language: str | None) -> list[dict]:
    violations: list[dict] = []
    for item in directories:
        selected = select_language(item, language)
        if selected is None:
            violations.append(
                {
                    "kind": "unknown_language",
                    "version": item.name,
                    "function": "",
                    "value": "",
                    "limit": "--language",
                }
            )
            continue
        found, metrics = check_item(item, selected)
        for line in metrics:
            print(f"{item.name} {line}")
        violations.extend({**finding, "item": item.name} for finding in found)
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", required=True, type=Path)
    parser.add_argument("--language", "--lang", choices=EXTENSIONS)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if not args.items.is_dir():
        parser.error(f"items directory does not exist: {args.items}")
    directories = item_directories(args.items)
    if not directories:
        parser.error(f"no item directories found under: {args.items}")
    try:
        violations = _run(directories, args.language)
    except SyntaxError as error:
        print(_error_line("syntax_error", str(error), "valid source"))
        return 2
    except SourceSyntaxError as error:
        print(_error_line("syntax_error", str(error), "valid source"))
        return 2
    except (RuntimeError, OSError, ValueError) as error:
        print(_error_line("grammar_error", str(error), "available grammar"))
        return 2
    if not args.check:
        return 0
    for violation in violations:
        print(json.dumps(violation, sort_keys=True))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
