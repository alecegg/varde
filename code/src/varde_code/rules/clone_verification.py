"""Verify exact-clone SQL candidates against parsed source trees."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Never

from ast_grep_py import SgRoot

from varde_code.parse import language_for_path, parse_source_for_path
from varde_code.rules.finding import Finding, finding_id
from varde_code.rules.model import Diagnostic, Rule

DEFAULT_MIN_TOKENS = 20
DEFAULT_MIN_MEMBERS = 3
DEFAULT_MIN_LINES = 8
BODY_KINDS = {
    "body",
    "block",
    "compound_statement",
    "statement_block",
    "suite",
    "do_block",
    "expression_body",
    "function_body",
}
RUST_LANG_NAMES = {
    "bash": "Bash",
    "c": "C",
    "cpp": "Cpp",
    "csharp": "CSharp",
    "css": "Css",
    "dart": "Dart",
    "go": "Go",
    "elixir": "Elixir",
    "haskell": "Haskell",
    "hcl": "Hcl",
    "html": "Html",
    "java": "Java",
    "javascript": "JavaScript",
    "json": "Json",
    "kotlin": "Kotlin",
    "lua": "Lua",
    "markdown": "Markdown",
    "nix": "Nix",
    "php": "Php",
    "python": "Python",
    "ruby": "Ruby",
    "rust": "Rust",
    "scala": "Scala",
    "solidity": "Solidity",
    "swift": "Swift",
    "tsx": "Tsx",
    "typescript": "TypeScript",
    "yaml": "Yaml",
}


def thresholds(rule: Rule) -> tuple[int, int, int]:
    values = []
    for name, default, minimum in (
        ("min_tokens", DEFAULT_MIN_TOKENS, 1),
        ("min_members", DEFAULT_MIN_MEMBERS, 2),
        ("min_span_lines", DEFAULT_MIN_LINES, 0),
    ):
        raw = (rule.thresholds or {}).get(name, default)
        if not math.isfinite(raw) or raw % 1 or raw < minimum or raw > 0xFFFFFFFF:
            raise ValueError(
                f"{name} must be an integer between {minimum} and {0xFFFFFFFF}"
            )
        values.append(int(raw))
    return tuple(values)  # type: ignore[return-value]


def _find_span(node: Any, start: int, end: int) -> Any | None:
    rng = node.range()
    if rng.start.index == start and rng.end.index == end:
        return node
    for child in node.children():
        child_range = child.range()
        if child_range.start.index <= start and child_range.end.index >= end:
            found = _find_span(child, start, end)
            if found is not None:
                return found
    return None


def _byte_to_character_index(text: str) -> dict[int, int]:
    result = {0: 0}
    byte_index = 0
    for character_index, character in enumerate(text, start=1):
        byte_index += len(character.encode("utf-8"))
        result[byte_index] = character_index
    return result


def _character_span(
    start_byte: int,
    end_byte: int,
    data_length: int,
    byte_to_character: dict[int, int],
) -> tuple[int, int] | str:
    start = byte_to_character.get(start_byte)
    end = byte_to_character.get(end_byte)
    if start is not None and end is not None:
        return start, end
    if max(start_byte, end_byte) > data_length:
        return "function span extends beyond source"
    return "function span does not align with a UTF-8 character boundary"


def _load_source(
    path: Path,
) -> tuple[Any, str, str, bytes, dict[int, int]] | str:
    try:
        language = language_for_path(path)
        if language is None:
            _raise_unsupported_clone_source()
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeError as error:
            raise ValueError(
                "source read failed: stream did not contain valid UTF-8"
            ) from error
        parsed = parse_source_for_path(language, path, text)
        if parsed.has_error():
            _raise_clone_parse_error()
        return (
            SgRoot(text, parsed.lang).root(),
            parsed.lang,
            text,
            data,
            _byte_to_character_index(text),
        )
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        if isinstance(error, OSError):
            return f"source read failed: {error}"
        return str(error)


def _raise_unsupported_clone_source() -> Never:
    raise ValueError("unsupported clone source")


def _raise_clone_parse_error() -> Never:
    raise ValueError("clone source has parse errors")


def _canonical(node: Any, output: bytearray) -> int:
    if node.kind() in {"comment", "line_comment", "block_comment"}:
        return 0
    kind = node.kind().encode()
    output.extend(b"N" + len(kind).to_bytes(4, "little") + kind)
    children = list(node.children())
    tokens = 0
    if not children:
        text = node.text().encode("utf-8")
        output.extend(b"T" + len(text).to_bytes(4, "little") + text)
        tokens = 1
    else:
        for child in children:
            tokens += _canonical(child, output)
    output.extend(b"E")
    return tokens


def _hash(data: bytes) -> int:
    value = 0xCBF29CE484222325
    for byte in data:
        value = ((value ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return value


def _key(finding: Finding) -> tuple[str, int, int]:
    span = finding.location.span
    return finding.location.file, span.start_byte, span.end_byte


def verify(
    rule: Rule, root: str | Path, candidates: list[Finding]
) -> tuple[list[Finding], list[Diagnostic]]:
    try:
        min_tokens, min_members, min_lines = thresholds(rule)
    except ValueError as error:
        return [], [Diagnostic(rule.id, "", str(error))]
    base = Path(root)
    sources: dict[Path, tuple[Any, str, str, bytes, dict[int, int]] | str] = {}
    groups: dict[bytes, tuple[int, list[Finding]]] = {}
    diagnostics = []
    for finding in candidates:
        path = Path(finding.location.file)
        if not path.is_absolute():
            path = base / path
        if path not in sources:
            source = _load_source(path)
            sources[path] = source
            if isinstance(source, str):
                diagnostics.append(Diagnostic(rule.id, finding.location.file, source))
        source = sources[path]
        if isinstance(source, str):
            continue
        parsed, parsed_language, _text, data, byte_to_character = source
        span = finding.location.span
        character_span = _character_span(
            span.start_byte, span.end_byte, len(data), byte_to_character
        )
        if isinstance(character_span, str):
            diagnostics.append(
                Diagnostic(rule.id, finding.location.file, character_span)
            )
            continue
        start, end = character_span
        node = _find_span(parsed, start, end)
        if node is None:
            diagnostics.append(
                Diagnostic(
                    rule.id,
                    finding.location.file,
                    "function span missing from source tree",
                )
            )
            continue
        body = next(
            (
                child
                for child in node.children()
                if child.is_named() and child.kind() in BODY_KINDS
            ),
            node,
        )
        language_name = RUST_LANG_NAMES.get(parsed_language)
        if language_name is None:
            diagnostics.append(
                Diagnostic(rule.id, finding.location.file, "unsupported clone source")
            )
            continue
        canonical = bytearray(f"L:{language_name};".encode())
        tokens = _canonical(body, canonical)
        if tokens < min_tokens or max(0, span.end_line - span.start_line) < min_lines:
            continue
        groups.setdefault(bytes(canonical), (tokens, []))[1].append(finding)
    output = []
    for canonical, (tokens, iter_members) in groups.items():
        iter_members.sort(key=_key)
        unique_members = []
        for item in iter_members:
            if not unique_members or _key(unique_members[-1]) != _key(item):
                unique_members.append(item)
        members = unique_members
        if len(members) < min_members:
            continue
        first = members[0]
        group = (
            f"exact-clone-{_hash(canonical):016x}:{first.location.file}:"
            f"{first.location.span.start_byte}"
        )
        locations = [
            {
                "file": item.location.file,
                "startLine": item.location.span.start_line,
                "endLine": item.location.span.end_line,
            }
            for item in members
        ]
        for item in members:
            item.evidence = {
                "verification": "exact-clone",
                "group": group,
                "label": group,
                "members": locations,
                "token_count": tokens,
                "min_tokens": min_tokens,
                "min_members": min_members,
                "min_span_lines": min_lines,
            }
            item.id = finding_id(item.rule_id, item.location.file, item.location.span)
            output.append(item)
    return sorted(output, key=_key), diagnostics
