"""Implementation of ``varde map extract``."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import TextIO

from varde_code.extract.entity import extract_file
from varde_code.model import Diagnostic, Entity, Symbol
from varde_code.parse import language_for_path


def help(path: str = "") -> str:
    """Return the committed Rust CLI help snapshot."""
    del path
    return files("varde_code").joinpath("help/map_extract.txt").read_text()


def run(argv: list[str], io: object | None = None) -> int:
    """Run the extract subcommand with arguments after the app name."""
    del io
    args = list(argv)
    if args and args[0] == "map":
        args.pop(0)
    if args and args[0] == "extract":
        args.pop(0)

    if any(arg in {"--help", "-h"} for arg in args):
        print(help(), end="")
        return 0

    verbose = "--verbose" in args or "-v" in args
    args = [arg for arg in args if arg not in {"--verbose", "-v"}]
    unsupported = next((arg for arg in args if arg.startswith("-")), None)
    if unsupported:
        _argument_error("unexpected", unsupported)
        return 2
    if not args:
        _argument_error("missing")
        return 2
    if len(args) > 1:
        _argument_error("unexpected", args[1])
        return 2

    _ = verbose  # The Rust command uses this only to initialize tracing.
    path = args[0]
    try:
        output = _extract_path(path)
    except (OSError, RuntimeError, ValueError) as error:
        _error_log(str(error), path)
        _print_json(_tool_error("extract_error", str(error)))
        return 1
    root = Path(path).parent
    has_root = bool(str(root)) and str(root) != "."
    if has_root:
        _compact_paths(output, str(root))
    _trim_spans(output)
    _print_json(_success(output, compact=has_root))
    return 0


class _ExtractModule:
    name = "code"

    def run(self, argv: list[str], io: object | None = None) -> int:
        return run(argv, io)

    def help(self, path: str = "") -> str:
        return help(path)


def register() -> _ExtractModule:
    """Return the module interface used by the app's entry point."""
    return _ExtractModule()


def _extract_path(path: str):
    root = Path(path)
    if not root.exists():
        raise ValueError(f"path does not exist: {path}")
    paths = (
        [root]
        if root.is_file()
        else sorted(
            item
            for item in root.rglob("*")
            if item.is_file() and ".git" not in item.parts
        )
    )
    entities: list[dict[str, object]] = []
    symbols: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    files: list[str] = []
    result: dict[str, object] = {
        "entities": entities,
        "symbols": symbols,
        "diagnostics": diagnostics,
        "files": files,
    }
    for file_id, file_path in enumerate(paths):
        display_path = str(file_path)
        files.append(display_path)
        language = language_for_path(file_path)
        if language is None:
            diagnostics.append(
                _diagnostic(
                    file_id, display_path, "unsupported file type — skipped", "info"
                )
            )
            continue
        try:
            source = file_path.read_text(encoding="utf-8")
        except OSError, UnicodeError:
            diagnostics.append(
                _diagnostic(
                    file_id, display_path, "binary or non-UTF-8 — skipped", "error"
                )
            )
            continue
        extracted = extract_file(display_path, source, language, file_id)
        entities.extend(_entity_data(entity) for entity in extracted.entities)
        symbols.extend(_record_data(symbol) for symbol in extracted.symbols)
        if extracted.has_parse_error:
            diagnostics.append(
                _diagnostic(
                    file_id,
                    display_path,
                    "syntax error — partial extract kept",
                    "warning",
                )
            )
    return result


def _diagnostic(
    file_id: int, path: str, message: str, severity: str
) -> dict[str, object]:
    return {"file_id": file_id, "path": path, "message": message, "severity": severity}


def _argument_error(kind: str, argument: str = "") -> None:
    if kind == "missing":
        print(
            "error: the following required arguments were not provided:\n  <PATH>\n",
            file=sys.stderr,
        )
        print("Usage: varde map extract <PATH>\n", file=sys.stderr)
    else:
        print(f"error: unexpected argument '{argument}' found\n", file=sys.stderr)
        if argument.startswith("-"):
            print(
                f"  tip: to pass '{argument}' as a value, use '-- {argument}'\n",
                file=sys.stderr,
            )
        print("Usage: varde map extract [OPTIONS] <PATH>\n", file=sys.stderr)
    print("For more information, try '--help'.", file=sys.stderr)


def _error_log(message: str, path: str) -> None:
    timestamp = (
        datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )
    print(
        f'{timestamp} ERROR varde_code: fatal error: {message} file="{path}"',
        file=sys.stderr,
    )


def _entity_data(entity: Entity) -> dict[str, object]:
    value = asdict(entity)
    value["kind"] = entity.kind.name.lower()
    value["span"] = asdict(entity.span)
    return {
        key: item
        for key, item in value.items()
        if item is not None and not (key == "is_test" and item is False)
    }


def _record_data(record: Symbol | Diagnostic) -> dict[str, object]:
    value = asdict(record)
    if isinstance(record, Symbol):
        value["kind"] = record.kind.name.lower()
        value["span"] = asdict(record.span)
    return {key: item for key, item in value.items() if item is not None}


def _success(data: object, *, compact: bool) -> dict[str, object]:
    return {
        "schema_version": 1,
        "ok": True,
        "outcome": "success",
        "data": data,
        "meta": {"compact": compact, "truncated": False},
    }


def _tool_error(code: str, message: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "ok": False,
        "outcome": "tool-error",
        "data": {"error": {"code": code, "message": message}},
        "meta": {"compact": False, "truncated": False},
    }


def _compact_paths(data: dict[str, object], root: str) -> None:
    prefix = f"{root}{os.sep}"
    files = data.get("files")
    if isinstance(files, list):
        data["files"] = [
            path.removeprefix(prefix) for path in files if isinstance(path, str)
        ]
    diagnostics = data.get("diagnostics")
    if isinstance(diagnostics, list):
        for diagnostic in diagnostics:
            if isinstance(diagnostic, dict) and isinstance(diagnostic.get("path"), str):
                diagnostic["path"] = diagnostic["path"].removeprefix(prefix)


def _trim_spans(value: object) -> None:
    if isinstance(value, dict):
        span = value.get("span")
        if isinstance(span, dict):
            for key in ("start_byte", "end_byte", "start_col", "end_col"):
                span.pop(key, None)
        for item in value.values():
            _trim_spans(item)
    elif isinstance(value, list):
        for item in value:
            _trim_spans(item)


def _print_json(value: object, stream: TextIO | None = None) -> None:
    print(
        json.dumps(value, separators=(",", ":"), sort_keys=True),
        file=stream or sys.stdout,
    )
