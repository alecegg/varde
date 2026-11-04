"""Render checks R1 (contrast), R3 (target size) and R6 (page errors); pure."""

from __future__ import annotations

import re
from typing import Any

from .contrast import (
    RGBA,
    composite,
    contrast_ratio,
    fails_threshold,
    parse_rgba,
    required_ratio,
)
from .registry import RULES_BY_ID
from .report import Finding
from .settings import Settings

CANVAS: RGBA = (255.0, 255.0, 255.0, 1.0)
MOBILE_MAX_WIDTH = 480
# Console noise that is not a page defect: the browser asking for a favicon.
NOISE_URL_SUFFIXES = ("/favicon.ico",)
# Failed loads from a page checked offline or from disk: the check environment,
# not the page. Real script errors (uncaught exceptions, console.error) still fail.
NOISE_PATTERNS = (
    (
        r"^Failed to load resource: net::ERR_(FILE_NOT_FOUND|NAME_NOT_RESOLVED|FAILED"
        r"|INVALID_URL|INTERNET_DISCONNECTED|BLOCKED_BY_CLIENT|CONNECTION_REFUSED)"
    ),
    r"^Access to \w+ at 'file:",
    r"^Failed to fetch dynamically imported module: file:",
)


def render_finding(rule: str, target: str, width: int, **fields: Any) -> Finding:
    return Finding(
        id=rule,
        severity=RULES_BY_ID[rule].severity,
        tier="rendered",
        file=target,
        width=width,
        **fields,
    )


def backdrop_colors(backdrop: dict[str, Any]) -> list[RGBA] | None:
    """Opaque colours the text may sit on, or None when they cannot be known.

    A gradient yields one colour per stop; a background image yields None.
    """
    if backdrop["image"] == "image":
        return None
    base = CANVAS
    for layer in reversed(backdrop["layers"]):
        base = composite(parse_rgba(layer), base)
    if backdrop["image"] != "gradient":
        return [base]
    stops = [composite(parse_rgba(stop), base) for stop in backdrop["stops"]]
    return stops or None


def text_ratio(text: dict[str, Any]) -> float | None:
    """The best contrast the text reaches over its backdrop, or None if unknown."""
    colors = backdrop_colors(text["backdrop"])
    foreground = parse_rgba(text["color"])
    if colors is None or foreground[3] == 0:
        return None
    return max(contrast_ratio(foreground, color) for color in colors)


def check_contrast(
    at_width: dict[str, Any], target: str, width: int, settings: Settings
) -> list[Finding]:
    """R1: text below its required contrast; a gradient fails on its best stop."""
    del settings
    found = []
    for text in at_width["texts"]:
        ratio = text_ratio(text)
        required = required_ratio(text["font_px"], text["weight"])
        if ratio is None or not fails_threshold(ratio, required):
            continue
        found.append(
            render_finding(
                "R1",
                target,
                width,
                selector=text["selector"],
                snippet=f"{ratio:.2f}:1 needs {required}:1: {text['text']}",
                message=(
                    f"Text contrast {ratio:.2f}:1 is below {required}:1 at {width}px."
                ),
            )
        )
    return found


def check_targets(
    at_width: dict[str, Any], target: str, width: int, settings: Settings
) -> list[Finding]:
    """R3: an interactive target under `min_target_px` at mobile width."""
    if width > MOBILE_MAX_WIDTH:
        return []
    minimum = settings.min_target_px
    # Sizes are rounded so 43.98px from sub-pixel layout is not a defect.
    sizes = {
        (c["selector"], round(c["width"]), round(c["height"]))
        for c in at_width["controls"]
        if not c["inline"]
    }
    small = {s for s in sizes if min(s[1], s[2]) < minimum}
    return [
        render_finding(
            "R3",
            target,
            width,
            selector=selector,
            snippet=f"{w}x{h}px",
            message=f"Target {w}x{h}px is under {minimum}px at {width}px.",
        )
        for selector, w, h in sorted(small)
    ]


def _is_noise(error: dict[str, str], patterns: tuple[str, ...]) -> bool:
    if error.get("url", "").endswith(NOISE_URL_SUFFIXES):
        return True
    return any(re.search(p, error["text"]) for p in (*NOISE_PATTERNS, *patterns))


def check_errors(
    at_width: dict[str, Any], target: str, width: int, settings: Settings
) -> list[Finding]:
    """R6: a console error or uncaught page error while the page loaded."""
    patterns = settings.ignore_console
    seen = {
        (e["kind"], e["text"]) for e in at_width["errors"] if not _is_noise(e, patterns)
    }
    return [
        render_finding(
            "R6",
            target,
            width,
            snippet=text[:120],
            message=f"Page {'error' if kind == 'pageerror' else 'console error'}: "
            f"{text[:120]}",
        )
        for kind, text in sorted(seen)
    ]


# R7 (rendered half) -------------------------------------------------------
MIN_FOCUS_RATIO = 2.95  # a 3:1 ring measured on antialiased pixels


def _best_change_ratio(changes: list[dict[str, Any]]) -> float:
    """The strongest contrast any changed pixel pair reaches; 1.0 with none."""
    return max(
        (
            contrast_ratio(parse_rgba(change["fg"]), parse_rgba(change["bg"]))
            for change in changes
        ),
        default=1.0,
    )


def check_focus(
    at_width: dict[str, Any], target: str, width: int, settings: Settings
) -> list[Finding]:
    """R7 rendered: a Tab stop whose focus change is under 3:1 or not visible."""
    del settings
    walk = at_width.get("focus")
    if not walk:
        return []
    found: dict[tuple[str, str], Finding] = {}
    for stop in walk["stops"]:
        if stop["changes"] is None:
            continue  # not measurable (no box, or the page blocked the decode)
        ratio = _best_change_ratio(stop["changes"])
        if ratio >= MIN_FOCUS_RATIO:
            continue
        what = "no visible focus change" if ratio == 1.0 else f"ring {ratio:.2f}:1"
        found[stop["selector"], what] = render_finding(
            "R7",
            target,
            width,
            selector=stop["selector"],
            snippet=what,
            message=f"Keyboard focus on {stop['selector']}: {what}, needs 3:1.",
        )
    return list(found.values())


def drop_shadowed_r7(findings: list[Finding]) -> list[Finding]:
    """Drop rendered R7 findings when the static R7 already reports the cause.

    The static half fires when no `:focus-visible` rule exists anywhere; the Tab
    walk would then repeat that for every stop.
    """
    if not any(f.id == "R7" and f.tier == "static" for f in findings):
        return findings
    return [f for f in findings if not (f.id == "R7" and f.tier == "rendered")]
