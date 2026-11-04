"""The ``find_pattern`` query mode."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ast_grep_py import SgRoot

from varde_code import OutputCapture
from varde_code.parse import EXTENSION_LANGUAGES, language_for_path
from varde_code.pattern_match import language_name
from varde_code.toz_bridge import PAGE_LIMIT, available, capture_items

from .modes import register_mode
from .params import QueryError, object_input, req_str

_DEFAULT_LIMIT = 100
_ACCEPTED_KEYS = {
    "repoRoot",
    "filePath",
    "file",
    "path",
    "pattern",
    "language",
    "fullMatches",
    "matchesLimit",
    "matchesOffset",
}
_INTERNAL_KEYS = {"mode", "dbPath"}


def _target(input: dict[str, Any]) -> Path:
    target = input.get("filePath")
    if not isinstance(target, str):
        target = input.get("file")
    if not isinstance(target, str):
        target = input.get("path")
    root = input.get("repoRoot")
    if target is None and root is None:
        raise QueryError("invalid_input", "missing filePath, path, or repoRoot")
    if target is None:
        target = root
    if not isinstance(target, str):
        raise QueryError("invalid_input", '"repoRoot" must be a string')
    path = Path(target)
    if not path.is_absolute() and isinstance(root, str):
        path = Path(root) / path
    return path


def _language(input: dict[str, Any], target: Path, is_directory: bool) -> str:
    value = input.get("language")
    if value is None:
        if is_directory:
            raise QueryError(
                "invalid_input", "language is required when searching a directory"
            )
        value = language_for_path(target)
        if value is None:
            raise QueryError("invalid_input", f"unsupported file type {target}")
    if not isinstance(value, str):
        raise QueryError("invalid_input", '"language" must be a string')
    try:
        return language_name(value)
    except ValueError as exc:
        raise QueryError("invalid_input", f"unsupported language {value!r}") from exc


def _match_rows(
    path: Path, pattern: str, language: str, display_path: str
) -> list[dict[str, Any]]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        message = f"{display_path}: {exc.strerror} (os error {exc.errno})"
        raise QueryError("file_error", message) from exc
    except UnicodeError:
        return []
    rows = []
    root = SgRoot(source, language_name(language)).root()
    names = sorted(set(re.findall(r"\$([A-Z][A-Z0-9_]*)", pattern)))
    for node in root.find_all({"rule": {"pattern": pattern}}):
        node_range = node.range()
        start = node_range.start
        end = node_range.end
        start_byte = len(source[: start.index].encode("utf-8"))
        end_byte = len(source[: end.index].encode("utf-8"))
        start_line = source.count("\n", 0, start.index) + 1
        end_line = source.count("\n", 0, end.index) + 1
        line_start = source.rfind("\n", 0, start.index) + 1
        end_line_start = source.rfind("\n", 0, end.index) + 1
        rows.append(
            {
                "kind": node.kind(),
                "text": node.text(),
                "span": {
                    "start_byte": start_byte,
                    "end_byte": end_byte,
                    "start_line": start_line,
                    "start_col": len(source[line_start : start.index].encode("utf-8")),
                    "end_line": end_line,
                    "end_col": len(source[end_line_start : end.index].encode("utf-8")),
                },
                "captures": {
                    name: {"text": captured.text()}
                    for name in names
                    if (captured := node.get_match(name)) is not None
                },
                "file": str(path),
            }
        )
    return rows


def _options(input: dict[str, Any]) -> tuple[bool, int, int]:
    full = input.get("fullMatches", False)
    if not isinstance(full, bool):
        raise QueryError("invalid_input", "fullMatches must be a boolean")
    limit = input.get("matchesLimit", _DEFAULT_LIMIT)
    offset = input.get("matchesOffset", 0)
    for name, value in (("matchesLimit", limit), ("matchesOffset", offset)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise QueryError("invalid_input", f"{name} must be a nonnegative integer")
    if limit == 0:
        raise QueryError("invalid_input", "matchesLimit must be greater than zero")
    return full, limit, offset


def find_pattern(
    input_value: dict[str, Any], capture: OutputCapture | None = None
) -> dict[str, Any]:
    input = object_input(input_value)
    unknown = sorted(input.keys() - _ACCEPTED_KEYS - _INTERNAL_KEYS)
    if unknown:
        accepted = ", ".join(sorted(_ACCEPTED_KEYS))
        raise QueryError(
            "invalid_input",
            f"unknown key {unknown[0]!r}; accepted: {accepted}",
        )
    pattern = req_str(input, "pattern")
    root = input.get("repoRoot")
    target = _target(input)
    is_directory = target.is_dir()
    language = _language(input, target, is_directory)
    full, limit, offset = _options(input)

    if is_directory:
        paths = sorted(
            path
            for path in target.rglob("*")
            if path.is_file() and path.suffix.lower().lstrip(".") in EXTENSION_LANGUAGES
        )
    else:
        paths = [target]
    matches = []
    for path in paths:
        display_path = input.get(
            "filePath", input.get("file", input.get("path", str(path)))
        )
        if (
            isinstance(display_path, str)
            and not Path(display_path).is_absolute()
            and isinstance(root, str)
        ):
            display_path = f"{root.rstrip('/')}/{display_path}"
        matches.extend(_match_rows(path, pattern, language, display_path))
    matches.sort(key=lambda item: (item["file"], item["span"]["start_byte"]))

    total = len(matches)
    toz = None
    if not full and offset == 0 and total > limit and available(capture):
        toz_rows = [
            {
                "file": item["file"],
                "kind": item["kind"],
                "preview": item["text"][:160],
                "span": item["span"],
            }
            for item in matches
        ]
        toz = capture_items(capture, "find_pattern", toz_rows)
        if toz is not None:
            toz["projection"] = "match_preview_160"
    effective_limit = (
        PAGE_LIMIT if toz is not None and "matchesLimit" not in input else limit
    )
    start = min(offset, total)
    end = total if full else min(start + effective_limit, total)
    truncated = start > 0 or end < total
    result: dict[str, Any] = {"matches": matches[start:end]}
    if truncated:
        guide: dict[str, Any] = {
            "truncated": {
                "matches": {
                    "shown": end - start,
                    "total": total,
                    "offset": start,
                    "limit": None if full else effective_limit,
                    "next_offset": end if end < total else None,
                    "request": "set matchesOffset to next_offset, or set "
                    "fullMatches to true"
                    if end < total
                    else "set fullMatches to true for all matches",
                }
            }
        }
        if toz is not None:
            guide["toz"] = toz
            handle = toz["handle"]
            guide["truncated"]["matches"]["toz_read"] = (
                f"varde run query --handle {handle} --lines "
                f"{end + 1}:{min(end + effective_limit, total)}"
            )
            guide["truncated"]["matches"]["toz_search"] = (
                f'varde run query --handle {handle} "<term>"'
            )
        result["guide"] = guide
    return result


register_mode("find_pattern", find_pattern)
