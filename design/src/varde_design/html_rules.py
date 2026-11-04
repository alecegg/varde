"""Static HTML rules: S1 kicker label, S5 document basics, S6 images, S8 placeholder
copy, R7 focus ring presence; plus the inline-CSS bridge (S2, S3, S4, S10).

Sources, clean-room ports of numbers only:
# S1 source: hallmark@4f6a46c sloplint.mjs:2241,2281-2289, MIT; impeccable@4f95649
#   kicker-above-heading, Apache-2.0.
# S5 source: hallmark@4f6a46c sloplint.mjs:3872 (F21), F23, MIT; impeccable
#   skipped-heading, Apache-2.0.
# S6 source: impeccable@4f95649 broken-image, Apache-2.0 (no hallmark or taste rule).
# S8 source: hallmark@4f6a46c sloplint.mjs:1445-1457, MIT; taste-skill lint.mjs:49, MIT.
# R7 source: hallmark@4f6a46c sloplint.mjs:1617-1619, MIT.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace

from .css_rules import check_css, parse_px
from .css_scanner import StyleRule, scan_css
from .html_scanner import Document, Element, StyleSource, parse_html
from .html_style import element_style
from .motion_rules import check_reduced_motion
from .registry import RULES_BY_ID, active_rules
from .report import Finding
from .settings import Settings

HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
KICKER_SKIP_TAGS = frozenset(
    [
        "a",
        "button",
        "label",
        "input",
        "select",
        "option",
        "li",
        "th",
        "td",
        "nav",
        "time",
        "code",
        "pre",
        "summary",
        "figcaption",
        "dt",
        "dd",
    ]
) | frozenset(HEADINGS)
BLOCK_TAGS = frozenset(
    ["div", "p", "ul", "ol", "section", "article", "header", "footer", "table", "form"]
)
KICKER_MAX_WORDS, KICKER_MAX_CHARS = 7, 56
KICKER_MIN_TRACKING_EM, KICKER_MAX_PX, KICKER_CAPS_RATIO = 0.04, 15.0, 0.6
KICKER_HEADING_RATIO = 1.5
BASE_PX = 16.0
PLACEHOLDER_SRC_MARKS = ("placeholder", "placehold.", "path/to/", "dummyimage")
PLACEHOLDER_SRC = ("", "#", "about:blank")
COPY_ATTRS = ("alt", "title", "placeholder", "aria-label", "href")
COPY_PATTERNS = (
    ("lorem ipsum", re.compile(r"\blorem ipsum\b|\bdolor sit amet\b", re.IGNORECASE)),
    ("TODO marker", re.compile(r"\bTODO\b")),
    ("example.com", re.compile(r"\bexample\.com\b", re.IGNORECASE)),
    (
        "placeholder name",
        re.compile(r"\b(jane doe|john smith|john doe|example user)\b", re.IGNORECASE),
    ),
)
INTERACTIVE_TAGS = ("a", "button", "input", "select", "textarea", "summary")
Check = Callable[["Context"], list[Finding]]


@dataclass(frozen=True)
class Context:
    doc: Document
    file: str
    settings: Settings
    sheets: tuple[tuple[StyleSource, tuple[StyleRule, ...]], ...]

    def block_rules(self) -> list[StyleRule]:
        """Rules from <style> elements, in source order."""
        return [r for src, rules in self.sheets if self.is_block(src) for r in rules]

    def inline_rule(self, element: Element) -> StyleRule | None:
        for src, rules in self.sheets:
            if src.owner == element.index and not self.is_block(src) and rules:
                return rules[0]
        return None

    def is_block(self, src: StyleSource) -> bool:
        return src.owner is not None and self.doc.elements[src.owner].tag == "style"


def make_finding(
    rule_id: str,
    ctx: Context,
    line: int,
    message: str,
    snippet: str = "",
    severity: str | None = None,
) -> Finding:
    return Finding(
        id=rule_id,
        severity=severity or RULES_BY_ID[rule_id].severity,
        tier="static",
        file=ctx.file,
        message=message,
        line=line,
        snippet=snippet,
    )


# S1 ----------------------------------------------------------------------


def caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum(c.isupper() for c in letters) / len(letters) if letters else 0.0


def font_px(style: dict[str, str]) -> float | None:
    return parse_px(style["font-size"]) if "font-size" in style else None


def tracking_em(style: dict[str, str], size: float | None) -> float | None:
    value = style.get("letter-spacing", "").strip().lower()
    if value.endswith("em") and not value.endswith("rem"):
        return _number(value.removesuffix("em"))
    px = parse_px(value) if value else None
    return None if px is None else px / (size or BASE_PX)


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def kicker_signals(text: str, style: dict[str, str]) -> int:
    """Count of the five kicker signals: caps, tracking, small, mono, small-caps."""
    size = font_px(style)
    tracking = tracking_em(style, size)
    uppercase = "uppercase" in style.get("text-transform", "")
    shouty = caps_ratio(text) >= KICKER_CAPS_RATIO
    return sum(
        [
            uppercase or shouty,
            tracking is not None and tracking >= KICKER_MIN_TRACKING_EM,
            size is not None and size <= KICKER_MAX_PX,
            "mono" in style.get("font-family", "").lower(),
            "small-caps" in style.get("font-variant-caps", "").lower(),
        ]
    )


def kicker_text_ok(text: str) -> bool:
    """Short, label-like text: at most 7 words and 56 characters, not a counter."""
    words = [w for w in re.split(r"[\s·/|—–]+", text) if w]
    if not words or len(words) > KICKER_MAX_WORDS or len(text) > KICKER_MAX_CHARS:
        return False
    if re.fullmatch(r"[\d.,]+\s*(?:[%°+]|[a-z]{1,3})", text, re.IGNORECASE):
        return False
    stripped = re.sub(r"^\s*(?:no\.?\s*)?\d{1,3}(?:\s*[·./—–-]\s*|\s+|$)", "", text)
    return sum(c.isdigit() for c in stripped) < 2


def kicker_element_ok(doc: Document, element: Element) -> bool:
    """Plain label element: not a link, control or live region, no block children."""
    if element.tag in KICKER_SKIP_TAGS or "for" in element.attrs:
        return False
    if element.attrs.get("aria-hidden") == "true" or "aria-live" in element.attrs:
        return False
    if element.attrs.get("role") == "status":
        return False
    below = [doc.elements[i].tag for i in _descendant_indexes(doc, element)]
    return not any(t in BLOCK_TAGS or t in ("br", "a", "img", "time") for t in below)


def _descendant_indexes(doc: Document, element: Element) -> list[int]:
    found, stack = [], list(element.children)
    while stack:
        index = stack.pop()
        found.append(index)
        stack += doc.elements[index].children
    return found


def check_s1(ctx: Context) -> list[Finding]:
    rules, doc = ctx.block_rules(), ctx.doc
    found = []
    for element in doc.elements:
        heading = doc.next_sibling(element)
        if heading is None or heading.tag not in HEADINGS:
            continue
        if not kicker_element_ok(doc, element):
            continue
        text = doc.descendants_text(element)
        style = element_style(element, rules, ctx.inline_rule(element))
        if not kicker_text_ok(text) or style.get("position") in ("absolute", "fixed"):
            continue
        head_style = element_style(heading, rules, ctx.inline_rule(heading))
        if not _heading_dominates(font_px(style), font_px(head_style)):
            continue
        if kicker_signals(text, style) >= 2:
            message = f"Tracked-caps label above <{heading.tag}>"
            found.append(make_finding("S1", ctx, element.line, message, text))
    return found


def _heading_dominates(label_px: float | None, heading_px: float | None) -> bool:
    if label_px is None or heading_px is None:
        return True
    return heading_px >= KICKER_HEADING_RATIO * label_px


# S5 ----------------------------------------------------------------------


def check_s5(ctx: Context) -> list[Finding]:
    doc = ctx.doc
    opinion = ctx.settings.profile == "opinion"  # h1 and heading steps: 36% labelled
    found = _skipped_headings(ctx) if opinion else []
    roots = doc.find("html")
    if not roots:
        return found
    root = roots[0]
    if not root.attrs.get("lang", "").strip():
        found.append(make_finding("S5", ctx, root.line, "Missing lang on <html>"))
    titles = [t for t in doc.find("title") if doc.descendants_text(t)]
    if not titles:
        found.append(make_finding("S5", ctx, root.line, "Missing or empty <title>"))
    if not any(m.attrs.get("name", "").lower() == "viewport" for m in doc.find("meta")):
        found.append(make_finding("S5", ctx, root.line, "Missing viewport meta"))
    if opinion and not doc.find("h1"):
        found.append(
            make_finding("S5", ctx, root.line, "No <h1> on the page", "", "warn")
        )
    return found


def _skipped_headings(ctx: Context) -> list[Finding]:
    found, previous = [], 0
    for element in ctx.doc.elements:
        if element.tag not in HEADINGS:
            continue
        level = int(element.tag[1])
        if previous and level > previous + 1:
            message = f"<h{previous}> is followed by <h{level}>"
            snippet = ctx.doc.descendants_text(element)[:40]
            found.append(
                make_finding("S5", ctx, element.line, message, snippet, "warn")
            )
        previous = level
    return found


# S6 ----------------------------------------------------------------------


def is_placeholder_src(src: str) -> bool:
    value = src.strip().lower()
    return value in PLACEHOLDER_SRC or any(m in value for m in PLACEHOLDER_SRC_MARKS)


def check_s6(ctx: Context) -> list[Finding]:
    found = []
    for img in ctx.doc.find("img"):
        if "alt" not in img.attrs:
            found.append(make_finding("S6", ctx, img.line, "<img> without alt text"))
        src = img.attrs.get("src", "")
        srcset_only = bool(img.attrs.get("srcset", "").strip()) and not src.strip()
        if is_placeholder_src(src) and not srcset_only:
            message = "<img> with an empty or placeholder src"
            found.append(make_finding("S6", ctx, img.line, message, src))
    return found


# S8 ----------------------------------------------------------------------


def placeholder_matches(text: str) -> list[tuple[str, str, int]]:
    """(label, matched text, newline count before it) for each placeholder pattern."""
    found = []
    for label, pattern in COPY_PATTERNS:
        match = pattern.search(text)
        if match:
            found.append((label, match.group(0), text.count("\n", 0, match.start())))
    return found


def check_s8(ctx: Context) -> list[Finding]:
    sources = [(n.text, n.line) for n in ctx.doc.texts]
    for element in ctx.doc.elements:
        sources += [
            (element.attrs[a], element.line) for a in COPY_ATTRS if a in element.attrs
        ]
    found = []
    for text, line in sources:
        for label, matched, extra in placeholder_matches(text):
            message = f"Placeholder copy: {label}"
            found.append(make_finding("S8", ctx, line + extra, message, matched))
    return found


# R7 (static half) --------------------------------------------------------


def has_focus_visible(ctx: Context) -> bool:
    """True when any style or Tailwind-style class supplies a focus-visible ring."""
    if any(":focus-visible" in src.css.lower() for src, _ in ctx.sheets):
        return True
    return any("focus-visible:" in e.attrs.get("class", "") for e in ctx.doc.elements)


def check_r7(ctx: Context) -> list[Finding]:
    """Fail when a full document has controls, no linked CSS, no :focus-visible."""
    roots = ctx.doc.find("html")
    if not roots or _links_stylesheet(ctx.doc):
        return []
    if not any(e.tag in INTERACTIVE_TAGS for e in ctx.doc.elements):
        return []
    if has_focus_visible(ctx):
        return []
    message = "No :focus-visible rule anywhere; keyboard focus has no ring"
    return [make_finding("R7", ctx, roots[0].line, message)]


def _links_stylesheet(doc: Document) -> bool:
    return any(
        "stylesheet" in link.attrs.get("rel", "").lower() for link in doc.find("link")
    )


HTML_CHECKS: dict[str, Check] = {
    "S1": check_s1,
    "S5": check_s5,
    "S6": check_s6,
    "S8": check_s8,
    "R7": check_r7,
}


# Entry point -------------------------------------------------------------


def _inline_findings(ctx: Context) -> list[Finding]:
    """Run the CSS rules over every <style> block and style attribute."""
    found = []
    for src, _ in ctx.sheets:
        owner = ctx.doc.elements[src.owner or 0]
        for finding in check_css(src.css, ctx.file, ctx.settings):
            line = (finding.line or 1) + src.line - 1
            selector = finding.selector if ctx.is_block(src) else f"{owner.tag}[style]"
            found.append(replace(finding, line=line, selector=selector))
    return found


def _reduced_motion(ctx: Context) -> list[Finding]:
    pairs = [(rule, src.line - 1) for src, rules in ctx.sheets for rule in rules]
    return check_reduced_motion(pairs, [src.css for src, _ in ctx.sheets], ctx.file)


def check_html(text: str, file: str, settings: Settings) -> list[Finding]:
    """Run every active HTML rule and the CSS rules over inline styles."""
    doc = parse_html(text)
    sheets = tuple((src, tuple(scan_css(src.css))) for src in doc.styles)
    ctx = Context(doc, file, settings, sheets)
    ids = {r.id for r in active_rules(settings.profile)} - set(settings.ignore)
    found = _inline_findings(ctx)
    if "S10" in ids:
        found += _reduced_motion(ctx)
    for rule_id, check in HTML_CHECKS.items():
        found += check(ctx) if rule_id in ids else []
    return sorted(found, key=lambda f: (f.line or 0, f.id))
