"""Mechanical page mutations with a known truth, for scoring `varde design check`.

Each mutation is a pure function `(html, rng) -> html | None` (None: not
applicable to this page). A defect mutation injects a defect that is true by
construction; a benign mutation changes the page without adding one. Injected
elements carry the class MARK so a finding can be matched to the mutated
element. No rule code is imported: the checker is only read through its JSON.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from dataclasses import dataclass

MARK = "mutx"
GIF = "data:image/gif;base64,R0lGODlhAQABAAAAACw="
PROBE_TEXT = "Contrast probe text for this page."
Mutation = Callable[[str, random.Random], "str | None"]


@dataclass(frozen=True)
class Family:
    name: str
    rule: str  # rule id, or "*" for a benign change scored against every rule
    kind: str  # "defect" or "benign"
    apply: Mutation
    rendered: bool = False  # needs the render tier
    targeted: bool = False  # the finding must name the MARK element


def luminance(gray: int) -> float:
    c = gray / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def ratio_on_white(gray: int) -> float:
    return 1.05 / (luminance(gray) + 0.05)


def gray_hex(low: float, high: float, rng: random.Random) -> str | None:
    grays = [g for g in range(256) if low <= ratio_on_white(g) <= high]
    if not grays:
        return None
    g = rng.choice(grays)
    return f"#{g:02x}{g:02x}{g:02x}"


def _at_body_end(html: str, fragment: str) -> str:
    i = html.lower().rfind("</body>")
    return html[:i] + fragment + html[i:] if i >= 0 else html + fragment


def _at_head_end(html: str, fragment: str) -> str | None:
    i = html.lower().find("</head>")
    return None if i < 0 else html[:i] + fragment + html[i:]


def _after_body_open(html: str, fragment: str) -> str | None:
    m = re.search(r"<body\b[^>]*>", html, re.IGNORECASE)
    return None if m is None else html[: m.end()] + fragment + html[m.end() :]


def _block(style: str, text: str, tag: str = "p") -> str:
    return f'<{tag} class="{MARK}" style="{style}">{text}</{tag}>'


def _sub_once(
    pattern: str, html: str, repl: str = "", flags: int = re.IGNORECASE | re.DOTALL
) -> str | None:
    out, n = re.subn(pattern, repl, html, count=1, flags=flags)
    return out if n else None


# ---- defects -------------------------------------------------------------


def s6_no_alt(html: str, rng: random.Random) -> str | None:
    return _at_body_end(html, f'<img class="{MARK}" src="{GIF}">')


def s5_no_lang(html: str, rng: random.Random) -> str | None:
    return _sub_once(
        r"(<html\b[^>]*?)\s+lang\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", html, r"\1"
    )


def s5_no_title(html: str, rng: random.Random) -> str | None:
    return _sub_once(r"<title\b[^>]*>.*?</title>", html)


def s5_no_viewport(html: str, rng: random.Random) -> str | None:
    return _sub_once(r"<meta\b[^>]*name\s*=\s*[\"']?viewport[^>]*>", html)


def s5_no_h1(html: str, rng: random.Random) -> str | None:
    if not re.search(r"<h1\b", html, re.IGNORECASE):
        return None
    return re.sub(r"<(/?)h1\b", r"<\1h2", html, flags=re.IGNORECASE)


def s5_skip_level(html: str, rng: random.Random) -> str | None:
    skip = f'<h4 class="{MARK}">Skipped level</h4>'
    if re.search(r"</h1>", html, re.IGNORECASE):
        return re.sub(r"</h1>", "</h1>" + skip, html, count=1, flags=re.IGNORECASE)
    return _after_body_open(html, "<h1>Probe</h1>" + skip)


def _contrast(low: float, high: float, size: int) -> Mutation:
    def apply(html: str, rng: random.Random) -> str | None:
        color = gray_hex(low, high, rng)
        style = f"margin:0;padding:8px;background:#fff;color:{color};font-size:{size}px"
        return None if color is None else _at_body_end(html, _block(style, PROBE_TEXT))

    return apply


def r2_wide(html: str, rng: random.Random) -> str | None:
    width = rng.choice([420, 500, 640, 900])
    return _at_body_end(
        html, _block(f"width:{width}px;height:12px;background:#ccc", "", "div")
    )


def _target(size: str, as_link: bool) -> Mutation:
    def apply(html: str, rng: random.Random) -> str | None:
        px = size if size != "small" else rng.choice([16, 20, 24, 32, 40])
        style = f"display:inline-block;width:{px}px;height:{px}px;padding:0;margin:0"
        if as_link:
            node = f'<a class="{MARK}" href="#" aria-label="Probe" style="{style};background:#ccc"></a>'  # noqa: E501
        else:
            node = (
                f'<button class="{MARK}" aria-label="Probe" style="{style}"></button>'
            )
        return _at_body_end(html, f"<div>{node}</div>")

    return apply


PROBE_LINK = f'<a class="{MARK}" href="#">Focus probe</a>'


def r7_outline_none(html: str, rng: random.Random) -> str | None:
    css = "<style>a:focus,button:focus,a:focus-visible{outline:none}</style>"
    head = _at_head_end(html, css)
    return None if head is None else _at_body_end(head, PROBE_LINK)


def r7_drop_ring(html: str, rng: random.Random) -> str | None:
    stripped, n = re.subn(r"[^{}<>]*:focus-visible[^{}]*\{[^{}]*\}", "", html)
    return _at_body_end(stripped, PROBE_LINK) if n else None


def r6_console_error(html: str, rng: random.Random) -> str | None:
    return _at_body_end(html, '<script>console.error("mutation probe")</script>')


def r6_throw(html: str, rng: random.Random) -> str | None:
    return _at_body_end(html, '<script>throw new Error("mutation probe")</script>')


def s4_tiny(html: str, rng: random.Random) -> str | None:
    px = rng.choice([8, 9, 10])
    text = "Updated hourly by the build pipeline for the platform team."
    return _at_body_end(html, _block(f"font-size:{px}px", text))


def s2_gradient_text(html: str, rng: random.Random) -> str | None:
    style = (
        "background:linear-gradient(90deg,#e11,#16e);-webkit-background-clip:text;"
        "background-clip:text;-webkit-text-fill-color:transparent;color:transparent"
    )
    return _at_body_end(html, _block(style, "Gradient headline", "h2"))


def s10_all_inline(html: str, rng: random.Random) -> str | None:
    return _at_body_end(
        html, _block("transition:all .2s ease;opacity:1", "Motion probe", "div")
    )


def s10_all_sheet(html: str, rng: random.Random) -> str | None:
    return _at_head_end(
        html, f"<style>.{MARK}-m{{transition: all 200ms ease-out}}</style>"
    )


def s10_slow(html: str, rng: random.Random) -> str | None:
    return _at_body_end(
        html, _block("transition:opacity 900ms ease", "Motion probe", "div")
    )


def s8_lorem(html: str, rng: random.Random) -> str | None:
    return _at_body_end(
        html, _block("", "Lorem ipsum dolor sit amet, consectetur adipiscing elit.")
    )


def s8_todo(html: str, rng: random.Random) -> str | None:
    return _at_body_end(html, _block("", "TODO: write the real copy for this section."))


# ---- benign --------------------------------------------------------------


def b_img_empty_alt(html: str, rng: random.Random) -> str | None:
    return _at_body_end(html, f'<img class="{MARK}" src="{GIF}" alt="">')


def b_img_alt(html: str, rng: random.Random) -> str | None:
    return _at_body_end(
        html, f'<img class="{MARK}" src="{GIF}" alt="Weekly deploys, rising">'
    )


def b_h2_after_h1(html: str, rng: random.Random) -> str | None:
    if not re.search(r"</h1>", html, re.IGNORECASE):
        return None
    return re.sub(
        r"</h1>",
        f'</h1><h2 class="{MARK}">Overview</h2>',
        html,
        count=1,
        flags=re.IGNORECASE,
    )


def b_title_text(html: str, rng: random.Random) -> str | None:
    return _sub_once(r"(<title\b[^>]*>).*?(</title>)", html, r"\1Renamed page\2")


def b_wide_ok(html: str, rng: random.Random) -> str | None:
    return _at_body_end(
        html,
        _block("width:100%;max-width:300px;height:12px;background:#ccc", "", "div"),
    )


def b_target_44(html: str, rng: random.Random) -> str | None:
    node = f'<button class="{MARK}" aria-label="Probe" style="width:44px;height:44px;padding:0"></button>'  # noqa: E501
    return _at_body_end(html, f"<div>{node}</div>")


def b_inline_link(html: str, rng: random.Random) -> str | None:
    return _at_body_end(
        html,
        f'<p>Read the <a class="{MARK}" href="#">full guide</a> before you start.</p>',
    )


def b_ring_added(html: str, rng: random.Random) -> str | None:
    css = "<style>:focus-visible{outline:3px solid #1a4fd6;outline-offset:2px}</style>"
    head = _at_head_end(html, css)
    return None if head is None else _at_body_end(head, PROBE_LINK)


def b_console_log(html: str, rng: random.Random) -> str | None:
    return _at_body_end(html, '<script>console.log("mutation probe")</script>')


def b_favicon_404(html: str, rng: random.Random) -> str | None:
    return _at_head_end(html, '<link rel="icon" href="missing-favicon.ico">')


def b_text_12(html: str, rng: random.Random) -> str | None:
    return _at_body_end(
        html, _block("font-size:12px", "Updated hourly by the build pipeline.")
    )


def b_gradient_box(html: str, rng: random.Random) -> str | None:
    style = "background:linear-gradient(90deg,#eee,#ddd);color:#111;padding:8px"
    return _at_body_end(html, _block(style, "Gradient panel, solid text", "div"))


def b_transition_prop(html: str, rng: random.Random) -> str | None:
    reduced = "<style>@media (prefers-reduced-motion:reduce){*{transition:none!important}}</style>"  # noqa: E501
    head = _at_head_end(html, reduced)
    block = _block("transition:opacity 200ms ease", "Motion probe", "div")
    return None if head is None else _at_body_end(head, block)


def b_plain_copy(html: str, rng: random.Random) -> str | None:
    return _at_body_end(
        html, _block("", "Deploys finished in four minutes on Tuesday.")
    )


def b_whitespace(html: str, rng: random.Random) -> str | None:
    opened = _after_body_open(html, "\n\n  ")
    return None if opened is None else _at_body_end(opened, "\n\n")


def b_comment(html: str, rng: random.Random) -> str | None:
    return _after_body_open(html, "<!-- mutation comment -->")


def b_class_rename(html: str, rng: random.Random) -> str | None:
    names = sorted(
        {
            t
            for m in re.findall(r'class="([^"]*)"', html)
            for t in m.split()
            if re.fullmatch(r"[a-z][a-z0-9-]{2,}", t)
        }
    )
    if not names:
        return None
    old = rng.choice(names)
    new = old + "-renamed"
    attr = re.sub(
        r'class="([^"]*)"',
        lambda m: (
            'class="'
            + " ".join(new if t == old else t for t in m.group(1).split())
            + '"'
        ),
        html,
    )
    css = re.sub(
        r"(<style\b[^>]*>)(.*?)(</style>)",
        lambda m: (
            m.group(1)
            + re.sub(rf"\.{re.escape(old)}(?![\w-])", "." + new, m.group(2))
            + m.group(3)
        ),
        attr,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return css if css != html else None


def b_reorder(html: str, rng: random.Random) -> str | None:
    pair = r"(<p\b[^>]*>[^<]*</p>)(\s*)(<p\b[^>]*>[^<]*</p>)"
    return _sub_once(pair, html, r"\3\2\1", re.IGNORECASE)


def b_text_swap(html: str, rng: random.Random) -> str | None:
    out = re.sub(
        r"(<p\b[^>]*>[^<]*?)\bthe\b", r"\1one", html, count=1, flags=re.IGNORECASE
    )
    return out if out != html else None


FAMILIES: tuple[Family, ...] = (
    Family("S6.no-alt", "S6", "defect", s6_no_alt, targeted=True),
    Family("S5.no-lang", "S5", "defect", s5_no_lang),
    Family("S5.no-title", "S5", "defect", s5_no_title),
    Family("S5.no-viewport", "S5", "defect", s5_no_viewport),
    Family("S5.no-h1", "S5", "defect", s5_no_h1),
    Family("S5.skip-level", "S5", "defect", s5_skip_level),
    Family("R1.normal-below-4.5", "R1", "defect", _contrast(3.0, 4.4, 16), True, True),
    Family("R1.large-below-3.0", "R1", "defect", _contrast(1.8, 2.9, 28), True, True),
    Family("R2.wider-than-390", "R2", "defect", r2_wide, True),
    Family("R3.button-small", "R3", "defect", _target("small", False), True, True),
    Family("R3.link-small", "R3", "defect", _target("small", True), True, True),
    Family("R7.outline-none", "R7", "defect", r7_outline_none, True),
    Family("R7.drop-ring-rules", "R7", "defect", r7_drop_ring),
    Family("R6.console-error", "R6", "defect", r6_console_error, True),
    Family("R6.uncaught-throw", "R6", "defect", r6_throw, True),
    Family("S4.tiny-prose", "S4", "defect", s4_tiny, targeted=True),
    Family("S2.gradient-clip", "S2", "defect", s2_gradient_text, targeted=True),
    Family("S10.all-inline", "S10", "defect", s10_all_inline),
    Family("S10.all-stylesheet", "S10", "defect", s10_all_sheet),
    Family("S10.slow-900ms", "S10", "defect", s10_slow),
    Family("S8.lorem", "S8", "defect", s8_lorem),
    Family("S8.todo", "S8", "defect", s8_todo),
    Family("S6.empty-alt", "S6", "benign", b_img_empty_alt),
    Family("S6.alt-text", "S6", "benign", b_img_alt),
    Family("S5.h2-after-h1", "S5", "benign", b_h2_after_h1),
    Family("S5.title-text", "S5", "benign", b_title_text),
    Family("R1.normal-4.6", "R1", "benign", _contrast(4.55, 4.8, 16), True),
    Family("R1.large-3.1", "R1", "benign", _contrast(3.05, 3.3, 28), True),
    Family("R2.width-ok", "R2", "benign", b_wide_ok, True),
    Family("R3.target-44", "R3", "benign", b_target_44, True),
    Family("R3.inline-link", "R3", "benign", b_inline_link, True),
    Family("R7.ring-added", "R7", "benign", b_ring_added),
    Family("R6.console-log", "R6", "benign", b_console_log, True),
    Family("R6.favicon-404", "R6", "benign", b_favicon_404, True),
    Family("S4.text-12px", "S4", "benign", b_text_12),
    Family("S2.gradient-box", "S2", "benign", b_gradient_box),
    Family("S10.transition-opacity", "S10", "benign", b_transition_prop),
    Family("S8.plain-copy", "S8", "benign", b_plain_copy),
    Family("any.whitespace", "*", "benign", b_whitespace),
    Family("any.comment", "*", "benign", b_comment),
    Family("any.class-rename", "*", "benign", b_class_rename),
    Family("any.reorder-paragraphs", "*", "benign", b_reorder),
    Family("any.text-swap", "*", "benign", b_text_swap),
)
