"""Design-token extraction: CSS text in, custom properties out. Pure; no I/O."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from .css_scanner import StyleRule, scan_css

MAX_SHEETS = 2000
MAX_ENTRIES = 100_000
MAX_SHEET_BYTES = 512 * 1024
MAX_VAR_DEPTH = 5
TOKEN_ROOT_WORDS = (":root", "[data-theme", "[data-color-scheme", "html")


@dataclass(frozen=True)
class Token:
    name: str
    value: str
    line: int
    selector: str


def is_token_selector(selector: str) -> bool:
    """True for a selector that declares global tokens (:root, html, themes)."""
    parts = [part.strip().lower() for part in selector.split(",")]
    return bool(parts) and all(part.startswith(TOKEN_ROOT_WORDS) for part in parts)


def extract_tokens(text: str) -> dict[str, Token]:
    """Custom properties declared in token selectors; the last declaration wins.

    A sheet over the byte cap yields nothing; entries stop at the entry cap.
    """
    if len(text.encode("utf-8", errors="ignore")) > MAX_SHEET_BYTES:
        return {}
    found: dict[str, Token] = {}
    for rule in scan_css(text):
        if is_token_selector(rule.selector):
            _add_tokens(found, rule)
    return found


def _add_tokens(found: dict[str, Token], rule: StyleRule) -> None:
    for decl in rule.declarations:
        if decl.prop.startswith("--") and len(found) < MAX_ENTRIES:
            found[decl.prop] = Token(decl.prop, decl.value, decl.line, rule.selector)


def collect_tokens(sheets: Iterable[str]) -> dict[str, Token]:
    """Merge tokens across sheets (later sheets win), reading at most MAX_SHEETS."""
    merged: dict[str, Token] = {}
    for index, text in enumerate(sheets):
        if index >= MAX_SHEETS:
            break
        merged.update(extract_tokens(text))
        if len(merged) >= MAX_ENTRIES:
            break
    return merged


def split_var(call: str) -> tuple[str, str | None]:
    """Name and fallback of the inside of var(...) text such as '--a, 4px'."""
    depth = 0
    for index, char in enumerate(call):
        depth += (char == "(") - (char == ")")
        if char == "," and depth == 0:
            return call[:index].strip(), call[index + 1 :].strip()
    return call.strip(), None


def var_spans(value: str) -> list[tuple[int, int]]:
    """(start, end) of each outermost var(...) call in value."""
    spans: list[tuple[int, int]] = []
    low = value.lower()
    pos = 0
    while (start := low.find("var(", pos)) >= 0:
        end = _close_paren(value, start + 3)
        spans.append((start, end + 1))
        pos = end + 1
    return spans


def _close_paren(value: str, open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(value)):
        depth += (value[index] == "(") - (value[index] == ")")
        if depth == 0:
            return index
    return len(value) - 1


def resolve(value: str, tokens: dict[str, Token], depth: int = MAX_VAR_DEPTH) -> str:
    """Substitute var() references up to depth levels; deeper ones stay as written."""
    spans = var_spans(value)
    if not spans or depth <= 0:
        return value
    out, pos = "", 0
    for start, end in spans:
        out += value[pos:start] + _resolve_call(value[start:end], tokens, depth)
        pos = end
    return out + value[pos:]


def _resolve_call(call: str, tokens: dict[str, Token], depth: int) -> str:
    name, fallback = split_var(call[4:-1])
    token = tokens.get(name)
    if token is not None:
        return resolve(token.value, tokens, depth - 1)
    if fallback is not None:
        return resolve(fallback, tokens, depth - 1)
    return call


def resolved_values(tokens: dict[str, Token]) -> dict[str, str]:
    return {name: resolve(token.value, tokens) for name, token in tokens.items()}


def usage_counts(text: str, tokens: dict[str, Token]) -> dict[str, int]:
    """How many var(--name) uses each token has in the declarations of text."""
    counter: Counter[str] = Counter()
    for rule in scan_css(text):
        for decl in rule.declarations:
            for start, end in var_spans(decl.value):
                counter[split_var(decl.value[start + 4 : end - 1])[0]] += 1
    return {name: counter[name] for name in tokens}
