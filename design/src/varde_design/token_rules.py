"""Token-aware CSS rules: S7 literals outside the token set, S9 off-scale spacing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from math import gcd

from .css_rules import parse_px
from .css_scanner import Declaration, StyleRule, scan_css
from .findings import style_finding
from .registry import active_rules
from .report import Finding
from .settings import Settings
from .tokens import Token, resolved_values, var_spans

DEFAULT_BASE_PX = 4
MIN_CHECKED_PX = 2.0
SPACING_PROPS = ("padding", "margin", "gap", "row-gap", "column-gap", "grid-gap")
SPACING_SIDES = ("top", "right", "bottom", "left", "inline", "block")
COLOR_PROPS = (
    "color",
    "background",
    "background-color",
    "background-image",
    "border",
    "border-color",
    "outline",
    "outline-color",
    "fill",
    "stroke",
    "box-shadow",
    "text-shadow",
    "caret-color",
    "accent-color",
)
NON_COLOR_BORDER_ENDS = ("radius", "width", "style", "offset")
SPACING_TOKEN = re.compile(r"^--(?:space|spacing|gap|sp|s)(?:[-_]?\d|[-_]|$)")
COLOR_LITERAL = re.compile(
    r"#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\([^)]*\)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TokenRuleResult:
    findings: list[Finding] = field(default_factory=list)
    not_run: list[str] = field(default_factory=list)


def is_spacing_prop(prop: str) -> bool:
    if prop in SPACING_PROPS:
        return True
    head, _, side = prop.partition("-")
    return head in ("padding", "margin") and side in SPACING_SIDES


def is_color_prop(prop: str) -> bool:
    if prop in COLOR_PROPS:
        return True
    border_part = prop.startswith(("border-", "outline-"))
    return border_part and not prop.endswith(NON_COLOR_BORDER_ENDS)


def without_vars(value: str) -> str:
    """value with every var(...) call removed, fallbacks included."""
    out, pos = "", 0
    for start, end in var_spans(value):
        out += value[pos:start] + " "
        pos = end
    return out + value[pos:]


def normalize_color(text: str) -> str:
    """Lower-case, space-free colour with 3/4-digit hex expanded to full length."""
    low = "".join(text.lower().split())
    if low.startswith("#") and len(low) in (4, 5):
        return "#" + "".join(char * 2 for char in low[1:])
    return low


def color_literals(value: str) -> list[str]:
    return [normalize_color(m) for m in COLOR_LITERAL.findall(without_vars(value))]


def length_parts(value: str) -> list[str]:
    return without_vars(value).replace("/", " ").split()


# S7 ----------------------------------------------------------------------


def token_color_set(values: dict[str, str]) -> set[str]:
    """Colour-valued tokens only; a spacing or font token is not a colour token."""
    return {
        normalize_color(v)
        for v in values.values()
        if COLOR_LITERAL.fullmatch(v.strip())
    }


def check_s7(rule: StyleRule, file: str, values: dict[str, str]) -> list[Finding]:
    """S7: colour literals outside the colour tokens; skipped without colour tokens.

    Radius literals are not checked: every labelled radius hit was an ordinary
    value, and a radius token set is rarely complete (sm, md, lg, pill).
    """
    colors = token_color_set(values)
    found: list[Finding] = []
    for decl in rule.declarations:
        message = s7_message(decl, colors)
        if message:
            found.append(style_finding("S7", file, rule, decl, message))
    return found


def s7_message(decl: Declaration, colors: set[str]) -> str:
    if decl.prop.startswith("--") or not colors or not is_color_prop(decl.prop):
        return ""
    bad = [c for c in color_literals(decl.value) if c not in colors]
    return f"Colour literal {', '.join(bad)} is not a token value" if bad else ""


# S9 ----------------------------------------------------------------------


def derive_base_px(values: dict[str, str]) -> int:
    """Greatest common divisor of whole-px spacing tokens; 0 when there are none."""
    base = 0
    for name, value in values.items():
        px = parse_px(value) if SPACING_TOKEN.match(name) else None
        if px is not None and px > 0 and px == int(px):
            base = gcd(base, int(px))
    return base


def off_scale(px: float, scale: tuple[int, ...] | None, base: int) -> bool:
    if scale is not None:
        return px not in scale
    return px % base != 0


def spacing_offenders(
    value: str, scale: tuple[int, ...] | None, base: int
) -> list[str]:
    bad = []
    for part in length_parts(value):
        px = parse_px(part)
        if (
            px is not None
            and abs(px) > MIN_CHECKED_PX
            and off_scale(abs(px), scale, base)
        ):
            bad.append(part)
    return bad


def check_s9(
    rule: StyleRule, file: str, scale: tuple[int, ...] | None, base: int
) -> list[Finding]:
    found = []
    for decl in rule.declarations:
        if not is_spacing_prop(decl.prop):
            continue
        bad = spacing_offenders(decl.value, scale, base)
        if bad:
            where = f"scale {list(scale)}" if scale else f"{base}px steps"
            message = f"Spacing {', '.join(bad)} is off the {where}"
            found.append(style_finding("S9", file, rule, decl, message))
    return found


# Entry point -------------------------------------------------------------


def check_token_rules(
    text: str, file: str, settings: Settings, tokens: dict[str, Token]
) -> TokenRuleResult:
    """Run S7 and S9 over text; S7 reports not run when there are no tokens."""
    wanted = {r.id for r in active_rules(settings.profile)} - set(settings.ignore)
    values = resolved_values(tokens)
    base = derive_base_px(values)
    if base == 0 and settings.profile == "opinion":
        base = DEFAULT_BASE_PX  # the 4px convention is a taste rule, opinion only
    result = TokenRuleResult()
    if "S7" in wanted and not tokens:
        result.not_run.append("S7: no tokens found")
    for rule in scan_css(text):
        if "S7" in wanted and tokens:
            result.findings.extend(check_s7(rule, file, values))
        if "S9" in wanted and (base or settings.spacing_scale):
            result.findings.extend(check_s9(rule, file, settings.spacing_scale, base))
    return result
