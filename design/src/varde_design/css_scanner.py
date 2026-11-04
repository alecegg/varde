"""CSS declaration scanner: text in, style rules out. Pure; no I/O, no cross-line regex.

Handles comments, strings, parentheses, and at-rules that wrap style rules
(media, supports, layer, container). Other at-rule bodies (font-face,
keyframes) are skipped. Declarations of nested rules are not reported.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

WRAPPING_AT_RULES = ("@media", "@supports", "@layer", "@container", "@scope")


@dataclass(frozen=True)
class Declaration:
    prop: str
    value: str
    line: int


@dataclass(frozen=True)
class StyleRule:
    selector: str
    line: int
    declarations: tuple[Declaration, ...]
    context: tuple[str, ...] = ()

    def last(self, prop: str) -> Declaration | None:
        """The winning declaration of prop within this block (the last one)."""
        found = [d for d in self.declarations if d.prop == prop]
        return found[-1] if found else None


def blank_comments(text: str) -> str:
    """Replace comment text with spaces, keeping newlines so line numbers hold."""
    out: list[str] = []
    index, quote = 0, ""
    while index < len(text):
        char = text[index]
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = len(text) if end < 0 else end + 2
            out.append("".join(c if c == "\n" else " " for c in text[index:end]))
            index = end
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _find_top_level(text: str, start: int, stops: str) -> int:
    """Index of the first stop char outside quotes and parentheses, or len(text)."""
    quote, depth = "", 0
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and char in stops:
            return index
    return len(text)


def _block_end(text: str, open_index: int) -> int:
    """Index of the brace closing the block opened at open_index, or len(text)."""
    depth, index = 0, open_index
    while index < len(text):
        index = _find_top_level(text, index, "{}")
        if index >= len(text):
            break
        depth += 1 if text[index] == "{" else -1
        if depth == 0:
            return index
        index += 1
    return len(text)


class _Lines:
    def __init__(self, text: str) -> None:
        self._breaks = [i for i, c in enumerate(text) if c == "\n"]

    def of(self, offset: int) -> int:
        return bisect_right(self._breaks, offset - 1) + 1


def _declarations(
    text: str, start: int, end: int, lines: _Lines
) -> tuple[Declaration, ...]:
    found: list[Declaration] = []
    pos = start
    while pos < end:
        stop = min(_find_top_level(text, pos, ";{"), end)
        if stop < end and text[stop] == "{":
            pos = min(_block_end(text, stop) + 1, end)
            continue
        found += _declaration(text[pos:stop], pos, lines)
        pos = stop + 1
    return tuple(found)


def _declaration(chunk: str, offset: int, lines: _Lines) -> list[Declaration]:
    prop, colon, value = chunk.strip().partition(":")
    if not colon or not prop.strip():
        return []
    value = value.strip()
    if value.lower().endswith("!important"):
        value = value[: -len("!important")].strip()
    first = offset + len(chunk) - len(chunk.lstrip())
    return [Declaration(prop.strip().lower(), value, lines.of(first))]


def _walk(
    text: str,
    start: int,
    end: int,
    context: tuple[str, ...],
    lines: _Lines,
    out: list[StyleRule],
) -> None:
    pos = start
    while pos < end:
        stop = min(_find_top_level(text, pos, ";{"), end)
        if stop >= end or text[stop] == ";":
            pos = stop + 1
            continue
        prelude = text[pos:stop].strip().lstrip("}").strip()
        if not prelude:
            pos = _block_end(text, stop) + 1
            continue
        close = min(_block_end(text, stop), end)
        first = pos + len(text[pos:stop]) - len(text[pos:stop].lstrip())
        if not prelude.startswith("@"):
            decls = _declarations(text, stop + 1, close, lines)
            out.append(StyleRule(prelude, lines.of(first), decls, context))
        elif prelude.lower().startswith(WRAPPING_AT_RULES):
            _walk(text, stop + 1, close, (*context, prelude), lines, out)
        pos = close + 1


def scan_css(text: str) -> list[StyleRule]:
    """Every style rule in text, in source order, with wrapping at-rules as context."""
    clean = blank_comments(text)
    rules: list[StyleRule] = []
    _walk(clean, 0, len(clean), (), _Lines(clean), rules)
    return rules
