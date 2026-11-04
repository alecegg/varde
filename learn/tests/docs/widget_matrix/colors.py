"""Colour maths for the matrix: parsing, alpha compositing, WCAG contrast."""

from __future__ import annotations

import re

RGBA = tuple[float, float, float, float]  # r, g, b in 0-255, alpha 0-1
_NUMBER = r"[-+]?\d*\.?\d+(?:e[-+]?\d+)?"
_RGB = re.compile(
    rf"^rgba?\(\s*({_NUMBER})[\s,]+({_NUMBER})[\s,]+({_NUMBER})"
    rf"(?:\s*[,/]\s*({_NUMBER})(%?))?\s*\)$"
)
_SRGB = re.compile(
    rf"^color\(\s*srgb\s+({_NUMBER})\s+({_NUMBER})\s+({_NUMBER})"
    rf"(?:\s*/\s*({_NUMBER})(%?))?\s*\)$"
)
CANVAS = {"light": (255.0, 255.0, 255.0, 1.0), "dark": (18.0, 18.0, 18.0, 1.0)}


def parse_color(text: str) -> RGBA | None:
    """RGBA of a computed `rgb()`, `rgba()` or `color(srgb ...)`; None otherwise."""
    value = text.strip().lower()
    if value == "transparent":
        return (0.0, 0.0, 0.0, 0.0)
    match = _RGB.match(value)
    scale = 1.0
    if not match:
        match, scale = _SRGB.match(value), 255.0
    if not match:
        return None
    r, g, b, alpha, percent = match.groups()
    a = 1.0 if alpha is None else float(alpha) / (100.0 if percent else 1.0)
    return (float(r) * scale, float(g) * scale, float(b) * scale, min(max(a, 0.0), 1.0))


def over(top: RGBA, below: RGBA) -> RGBA:
    """`top` composited over `below` (source-over)."""
    alpha = top[3] + below[3] * (1 - top[3])
    if alpha == 0:
        return (0.0, 0.0, 0.0, 0.0)
    mixed = tuple(
        (top[i] * top[3] + below[i] * below[3] * (1 - top[3])) / alpha for i in range(3)
    )
    return (mixed[0], mixed[1], mixed[2], alpha)


def backdrop(layers: list[str], scheme: str) -> RGBA | None:
    """Opaque colour behind an element.

    `layers` holds background colours innermost first. None when one cannot be
    parsed, so the caller skips instead of guessing.
    """
    colour = CANVAS[scheme]
    for text in reversed(layers):
        parsed = parse_color(text)
        if parsed is None:
            return None
        colour = over(parsed, colour)
    return colour


def luminance(colour: RGBA) -> float:
    def channel(value: float) -> float:
        v = value / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in colour[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(first: RGBA, second: RGBA) -> float:
    """WCAG contrast of two opaque colours."""
    hi, lo = sorted((luminance(first), luminance(second)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def ratio_over(fg_text: str, layers: list[str], scheme: str, opacity: float = 1.0):
    """Contrast of a possibly translucent foreground over its real backdrop."""
    fg, base = parse_color(fg_text), backdrop(layers, scheme)
    if fg is None or base is None:
        return None
    fg = (fg[0], fg[1], fg[2], fg[3] * opacity)
    return contrast_ratio(over(fg, base), base)
