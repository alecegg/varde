"""Static CSS rules: S2 gradient text, S3 accent side border, S4 tiny text, S10."""

from __future__ import annotations

import re
from collections.abc import Callable

from .css_scanner import Declaration, StyleRule, scan_css
from .findings import style_finding
from .motion_rules import check_s10
from .registry import active_rules
from .report import Finding
from .settings import Settings

REM_PX = 16.0
UI_SELECTOR_WORDS = (
    "button",
    "input",
    "select",
    "textarea",
    "label",
    "nav",
    "badge",
    "tab",
    "chip",
    "tag",
    "btn",
    "menu",
    "caption",
)
PROSE_TAGS = ("p", "li", "blockquote", "dd", "article", "body", "html", "main")
NEUTRAL_COLORS = ("transparent", "currentcolor", "inherit", "initial", "unset", "none")
GRAY_NAMES = ("black", "white", "gray", "grey", "silver", "gainsboro", "whitesmoke")
ACCENT_MIN_PX, ACCENT_MIN_ROUNDED_PX = 4.0, 2.0
Check = Callable[[StyleRule, str, Settings], list[Finding]]


def parse_px(value: str) -> float | None:
    """Pixel size of a plain px or rem length; None for anything else."""
    text = value.strip().lower()
    for unit, factor in (("px", 1.0), ("rem", REM_PX)):
        number = text.removesuffix(unit)
        if text.endswith(unit) and _is_number(number):
            return float(number) * factor
    return None


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


# S2 ----------------------------------------------------------------------


def check_s2(rule: StyleRule, file: str, settings: Settings) -> list[Finding]:
    clips = [rule.last("background-clip"), rule.last("-webkit-background-clip")]
    clipped = [d for d in clips if d and d.value.lower() == "text"]
    if not clipped or not _has_gradient(rule):
        return []
    message = "Gradient text via background-clip: text"
    return [style_finding("S2", file, rule, clipped[-1], message)]


def _has_gradient(rule: StyleRule) -> bool:
    paint = [
        d for d in rule.declarations if d.prop in ("background", "background-image")
    ]
    return any("gradient(" in d.value.lower() for d in paint)


# S3 ----------------------------------------------------------------------


def _is_rounded(rule: StyleRule) -> bool:
    for decl in rule.declarations:
        if decl.prop.endswith("radius") and _radius_is_positive(decl.value):
            return True
    return False


def _radius_is_positive(value: str) -> bool:
    parts = value.replace("/", " ").split()
    return any(
        parse_px(p) not in (None, 0.0) or p.endswith("%") and p != "0%" for p in parts
    )


def _is_accent(color: str) -> bool:
    text = color.strip().lower()
    if text in NEUTRAL_COLORS or text in GRAY_NAMES:
        return False
    if text.startswith("#"):
        return not _gray_hex(text[1:])
    return True


def _gray_hex(digits: str) -> bool:
    if len(digits) in (3, 4):
        digits = "".join(c * 2 for c in digits[:3])
    if len(digits) in (6, 8):
        return digits[0:2] == digits[2:4] == digits[4:6]
    return False


def _side_border(decl: Declaration) -> tuple[float, str] | None:
    """(width px, colour) of a side border; None without both."""
    width, colour = None, ""
    for part in _split_top_level(decl.value):
        parsed = parse_px(part)
        if parsed is not None:
            width = parsed
        elif part.lower() not in ("solid", "dashed", "dotted", "double", "none"):
            colour = part
    if "none" in decl.value.lower().split() or width is None or not colour:
        return None
    return width, colour


def _split_top_level(value: str) -> list[str]:
    parts, depth, current = [], 0, ""
    for char in value:
        depth += (char == "(") - (char == ")")
        if char == " " and depth == 0:
            parts += [current] if current else []
            current = ""
        else:
            current += char
    return parts + ([current] if current else [])


def check_s3(rule: StyleRule, file: str, settings: Settings) -> list[Finding]:
    rounded = _is_rounded(rule)
    limit = ACCENT_MIN_ROUNDED_PX if rounded else ACCENT_MIN_PX
    found = []
    for side in ("border-left", "border-right"):
        decl = rule.last(side)
        border = _side_border(decl) if decl else None
        if decl and border and border[0] >= limit and _is_accent(border[1]):
            message = f"Accent side border of {border[0]:g}px (limit {limit:g}px)"
            found.append(style_finding("S3", file, rule, decl, message))
    return found


# S4 ----------------------------------------------------------------------


def is_prose_selector(selector: str) -> bool:
    """True when the selector names a reading element (a tag, not a bare class)."""
    tags = re.findall(r"(?:^|[\s>+~,])([a-z][a-z0-9]*)(?![\w-])", selector.lower())
    return any(tag in PROSE_TAGS for tag in tags)


def is_ui_selector(selector: str) -> bool:
    """UI text unless the selector targets a prose tag: class-only names are unknown."""
    text = selector.lower()
    named_ui = any(word in text for word in UI_SELECTOR_WORDS)
    return named_ui or not is_prose_selector(selector)


def check_s4(rule: StyleRule, file: str, settings: Settings) -> list[Finding]:
    decl = rule.last("font-size")
    size = parse_px(decl.value) if decl else None
    if decl is None or size is None or size <= 0:
        return []
    ui = is_ui_selector(rule.selector)
    minimum = settings.min_ui_text_px if ui else settings.min_text_px
    if size >= minimum:
        return []
    kind = "UI" if ui else "prose"
    message = f"{kind} text of {size:g}px is under {minimum}px"
    return [style_finding("S4", file, rule, decl, message)]


CHECKS: dict[str, Check] = {
    "S2": check_s2,
    "S3": check_s3,
    "S4": check_s4,
    "S10": check_s10,
}


def check_css(text: str, file: str, settings: Settings) -> list[Finding]:
    """Run every active CSS rule over text; ignored rule ids are dropped."""
    wanted = [r.id for r in active_rules(settings.profile) if r.id in CHECKS]
    wanted = [rule_id for rule_id in wanted if rule_id not in settings.ignore]
    findings: list[Finding] = []
    for rule in scan_css(text):
        for rule_id in wanted:
            findings += CHECKS[rule_id](rule, file, settings)
    return findings
