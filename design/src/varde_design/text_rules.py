"""Render checks R4 (headline lines), R5 (declared font) and R8 (line length); pure.

Sources: R4 taste-skill `headline-lines` (an opinion, profile `opinion`); R5 taste
M8; R8 hallmark@4f6a46c sloplint.mjs:1602 (45 to 75 characters, 28 for a
one-sentence lede). The numbers are ported; the code is original.
"""

from __future__ import annotations

from typing import Any

from .render_rules import render_finding
from .report import Finding
from .settings import Settings

MAX_HEADLINE_LINES = 2
LEDE_MIN_CHARS = 28
FIRST_LINE_CAP = 200
# The first-line count is a rough measure: allow 15 percent over the limit.
LINE_TOLERANCE = 1.15


def check_headlines(
    at_width: dict[str, Any], target: str, width: int, settings: Settings
) -> list[Finding]:
    """R4: a headline (h1) wrapping onto more than two lines."""
    del settings
    return [
        render_finding(
            "R4",
            target,
            width,
            selector=h["selector"],
            snippet=f"{h['lines']} lines: {h['text']}",
            message=f"Headline wraps to {h['lines']} lines at {width}px.",
        )
        for h in at_width["headings"]
        if h["lines"] > MAX_HEADLINE_LINES
    ]


BARE_GENERICS = ("serif", "sans-serif", "monospace", "cursive", "fantasy")


def _has_designed_fallback(stack: str) -> bool:
    """True when the stack names a family (or system-ui) after the first.

    `Inter, system-ui, sans-serif` is a chosen graceful fallback, not a defect;
    `Inter, sans-serif` leaves the browser default look.
    """
    later = [f.strip().strip("\"'").lower() for f in stack.split(",")[1:]]
    return any(f and f not in BARE_GENERICS for f in later)


def check_fonts(
    at_width: dict[str, Any], target: str, width: int, settings: Settings
) -> list[Finding]:
    """R5: the first declared font family is not the one that rendered."""
    del settings
    return [
        render_finding(
            "R5",
            target,
            width,
            selector=font["selector"],
            snippet=font["stack"],
            message=(
                f"Declared font '{font['first']}' did not render; "
                f"{font['count']} text elements use a fallback."
            ),
        )
        for font in at_width["fonts"]
        if font["available"] is False and not _has_designed_fallback(font["stack"])
    ]


def _is_lede(paragraph: dict[str, Any]) -> bool:
    return paragraph["sentences"] <= 1


def _line_problem(paragraph: dict[str, Any], settings: Settings) -> str | None:
    """Why the first line of a paragraph is outside the reading range, or None."""
    chars = paragraph["first_line_chars"]
    if chars > settings.max_line_chars * LINE_TOLERANCE:
        shown = f"over {FIRST_LINE_CAP}" if chars >= FIRST_LINE_CAP else str(chars)
        return f"{shown} characters per line, over {settings.max_line_chars}"
    if paragraph["lines"] < 2:
        return None  # a single short line is a label or caption, not a measure
    floor = LEDE_MIN_CHARS if _is_lede(paragraph) else settings.min_line_chars
    if chars < floor:
        return f"{chars} characters per line, under {floor}"
    return None


def check_line_length(
    at_width: dict[str, Any], target: str, width: int, settings: Settings
) -> list[Finding]:
    """R8: reading paragraphs outside the line-length range at the widest width."""
    if not at_width.get("widest", True):
        return []
    found = []
    for paragraph in at_width["paragraphs"]:
        problem = _line_problem(paragraph, settings)
        if problem is None:
            continue
        found.append(
            render_finding(
                "R8",
                target,
                width,
                selector=paragraph["selector"],
                snippet=problem,
                message=f"Paragraph has {problem} at {width}px.",
            )
        )
    return found
