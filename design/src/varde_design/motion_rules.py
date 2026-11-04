"""S10 motion defects: per-rule checks plus the document-wide reduced-motion check.

# source: hallmark@4f6a46c sloplint.mjs:1320 (transition: all), :1366-1372
# (overshoot easing), :1279-1290 (hero in vh), :1389-1403 (layout animation), MIT.
# The clean-room Python port keeps the numbers only; severities follow the plan.
"""

from __future__ import annotations

import re

from .css_scanner import Declaration, StyleRule
from .findings import style_finding
from .report import Finding
from .settings import Settings

LAYOUT_PROPS = (
    "width",
    "height",
    "min-width",
    "min-height",
    "max-width",
    "max-height",
    "top",
    "left",
    "right",
    "bottom",
    "margin",
    "padding",
    "gap",
    "flex-basis",
)
OVERSHOOT_LOW, OVERSHOOT_HIGH = -0.05, 1.05
_BEZIER = re.compile(r"cubic-bezier\(([^)]*)\)", re.IGNORECASE)
_TIME = re.compile(r"^(\d*\.?\d+)(ms|s)$", re.IGNORECASE)
_VH = re.compile(r"\d\s*vh\b", re.IGNORECASE)
_MOTION_PROPS = ("transition", "animation")


def split_commas(value: str) -> list[str]:
    """Split on commas outside parentheses."""
    parts, depth, current = [], 0, ""
    for char in value:
        depth += (char == "(") - (char == ")")
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    return [*parts, current.strip()] if current.strip() or parts else []


def duration_ms(token: str) -> float | None:
    """Milliseconds of a CSS time token such as 200ms or 0.3s; None otherwise."""
    match = _TIME.match(token.strip())
    if not match:
        return None
    number = float(match.group(1))
    return number if match.group(2).lower() == "ms" else number * 1000


def segment_tokens(segment: str) -> list[str]:
    """Whitespace tokens of one transition segment, keeping function calls whole."""
    return re.findall(r"[^\s(]+(?:\([^)]*\))?", segment)


def transition_durations(value: str) -> list[float]:
    """First time token of each comma segment (the duration; the second is a delay)."""
    found = []
    for segment in split_commas(value):
        times = [t for t in map(duration_ms, segment_tokens(segment)) if t is not None]
        found += times[:1]
    return found


def transition_properties(decl: Declaration) -> list[str]:
    """Property names a transition or transition-property declaration targets."""
    if decl.prop == "transition-property":
        return [p.lower() for p in split_commas(decl.value)]
    if decl.prop != "transition":
        return []
    names = []
    for segment in split_commas(decl.value):
        tokens = segment_tokens(segment)
        words = [t for t in tokens if duration_ms(t) is None and "(" not in t]
        names += [w.lower() for w in words[:1]]
    return names


def overshoots(value: str) -> list[str]:
    """cubic-bezier() calls in value whose y1 or y2 leaves [-0.05, 1.05]."""
    bad = []
    for match in _BEZIER.finditer(value):
        numbers = [p.strip() for p in match.group(1).split(",")]
        if len(numbers) != 4:
            continue
        try:
            ys = (float(numbers[1]), float(numbers[3]))
        except ValueError:
            continue
        if any(y < OVERSHOOT_LOW or y > OVERSHOOT_HIGH for y in ys):
            bad.append(match.group(0))
    return bad


def is_layout_prop(name: str) -> bool:
    return any(name == p or name.startswith(p + "-") for p in LAYOUT_PROPS)


def check_s10(rule: StyleRule, file: str, settings: Settings) -> list[Finding]:
    found: list[Finding] = []
    for decl in rule.declarations:
        found += _transition_findings(rule, decl, file, settings)
        found += _easing_findings(rule, decl, file)
    found += _hero_findings(rule, file)
    return found


def _transition_findings(
    rule: StyleRule, decl: Declaration, file: str, settings: Settings
) -> list[Finding]:
    names = transition_properties(decl)
    found = []
    if "all" in names:
        message = f"{decl.prop}: all; list the properties explicitly"
        found.append(style_finding("S10", file, rule, decl, message, "fail"))
    layout = [n for n in names if is_layout_prop(n)]
    if layout:
        message = f"Transition animates layout property {layout[0]}"
        found.append(style_finding("S10", file, rule, decl, message, "warn"))
    if decl.prop == "transition":
        longest = max(transition_durations(decl.value), default=0.0)
        if longest > settings.max_motion_ms:
            message = f"Transition of {longest:g}ms exceeds {settings.max_motion_ms}ms"
            found.append(style_finding("S10", file, rule, decl, message, "warn"))
    return found


def _easing_findings(rule: StyleRule, decl: Declaration, file: str) -> list[Finding]:
    if not decl.prop.startswith(_MOTION_PROPS):
        return []
    return [
        style_finding("S10", file, rule, decl, f"Overshoot easing {call}", "fail")
        for call in overshoots(decl.value)
    ]


def _hero_findings(rule: StyleRule, file: str) -> list[Finding]:
    if "hero" not in rule.selector.lower():
        return []
    found = []
    for prop in ("height", "min-height"):
        decl = rule.last(prop)
        if decl and _VH.search(decl.value):
            message = f"Hero {prop} in vh; use dvh or svh"
            found.append(style_finding("S10", file, rule, decl, message, "warn"))
    return found


def check_reduced_motion(
    rules: list[tuple[StyleRule, int]], css_texts: list[str], file: str
) -> list[Finding]:
    """Warn once when motion exists and no prefers-reduced-motion query does.

    rules pairs each style rule with the line offset to add to its declaration lines.
    """
    if any("prefers-reduced-motion" in text.lower() for text in css_texts):
        return []
    for rule, offset in rules:
        for decl in rule.declarations:
            if decl.prop.startswith(_MOTION_PROPS) and _has_motion(decl):
                shifted = Declaration(decl.prop, decl.value, decl.line + offset)
                message = "Motion without a prefers-reduced-motion rule"
                return [style_finding("S10", file, rule, shifted, message, "warn")]
    return []


def _has_motion(decl: Declaration) -> bool:
    return decl.value.strip().lower() not in ("none", "0s", "0ms")
