"""WCAG contrast math over computed colours (pure; no browser)."""

from __future__ import annotations

import re

RGBA = tuple[float, float, float, float]

NORMAL_RATIO = 4.5
LARGE_RATIO = 3.0
FAIL_MARGIN = 0.05
LARGE_PX = 24
LARGE_BOLD_PX = 18
BOLD_WEIGHT = 700

_NUMBER = r"[-+]?\d*\.?\d+"
_FUNCTIONAL = re.compile(
    rf"rgba?\(\s*({_NUMBER})[\s,]+({_NUMBER})[\s,]+({_NUMBER})(?:[\s,/]+({_NUMBER})(%?))?\s*\)"
)


def parse_rgba(text: str) -> RGBA:
    """Parse `rgb(r, g, b)` or `rgba(r, g, b, a)` (comma or space separated)."""
    match = _FUNCTIONAL.fullmatch(text.strip().lower())
    if match is None:
        raise ValueError(f"unsupported colour: {text!r}")
    red, green, blue, alpha, percent = match.groups()
    alpha_value = 1.0 if alpha is None else float(alpha) / (100 if percent else 1)
    return (float(red), float(green), float(blue), min(max(alpha_value, 0.0), 1.0))


def composite(foreground: RGBA, background: RGBA) -> RGBA:
    """Source-over of foreground on background; the result alpha is combined."""
    f_alpha, b_alpha = foreground[3], background[3]
    out_alpha = f_alpha + b_alpha * (1 - f_alpha)
    if out_alpha == 0:
        return (0.0, 0.0, 0.0, 0.0)
    channels = tuple(
        (foreground[i] * f_alpha + background[i] * b_alpha * (1 - f_alpha)) / out_alpha
        for i in range(3)
    )
    return (channels[0], channels[1], channels[2], out_alpha)


def _channel(value: float) -> float:
    scaled = value / 255
    return scaled / 12.92 if scaled <= 0.04045 else ((scaled + 0.055) / 1.055) ** 2.4


def relative_luminance(color: RGBA) -> float:
    return (
        0.2126 * _channel(color[0])
        + 0.7152 * _channel(color[1])
        + 0.0722 * _channel(color[2])
    )


def contrast_ratio(foreground: RGBA, background: RGBA) -> float:
    """Ratio of two opaque colours; a translucent foreground is composited first."""
    shown = composite(foreground, background) if foreground[3] < 1 else foreground
    light, dark = sorted(
        (relative_luminance(shown), relative_luminance(background)), reverse=True
    )
    return (light + 0.05) / (dark + 0.05)


def is_large_text(font_px: float, weight: int) -> bool:
    return font_px >= LARGE_PX or (font_px >= LARGE_BOLD_PX and weight >= BOLD_WEIGHT)


def required_ratio(font_px: float, weight: int) -> float:
    return LARGE_RATIO if is_large_text(font_px, weight) else NORMAL_RATIO


def fails_threshold(ratio: float, required: float) -> bool:
    """True when the ratio is below the requirement by more than the margin."""
    return ratio < required - FAIL_MARGIN
