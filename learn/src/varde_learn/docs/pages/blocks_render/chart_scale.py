"""Pure number helpers for the chart renderer: nice ticks, formatting, thinning."""

import math

CHAR = 8.4  # average glyph width in viewBox units at the chart's 15-unit font


def fmt(value: float, decimals: int | None = None) -> str:
    """A number for people: thousands separators, trailing zeros trimmed."""
    if decimals is not None:
        text = f"{value:,.{decimals}f}"
    else:
        text = f"{value:,.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def raw(value: float) -> str:
    """A number for CSV: no separators."""
    return format(value, ".10g")


def compact(value: float, decimals: int | None = None) -> str:
    """Axis tick text: 12000 becomes 12k, 1500000 becomes 1.5M."""
    for size, suffix in ((1e9, "G"), (1e6, "M"), (1e4, "k")):
        if abs(value) >= size:
            scaled = value / (size if suffix != "k" else 1e3)
            return fmt(round(scaled, 1), None) + suffix
    return fmt(value, decimals)


def ellipsize(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(limit - 1, 1)] + "…"


def _step_for(span: float, target: int) -> float:
    raw_step = span / max(target, 1)
    magnitude = 10 ** math.floor(math.log10(raw_step))
    for factor in (1, 2, 5, 10):
        if raw_step <= factor * magnitude:
            return factor * magnitude
    return 10 * magnitude


def nice_ticks(low: float, high: float, target: int = 5) -> list[float]:
    """Round tick values that cover [low, high]; equal ends are widened first."""
    if high <= low:
        pad = abs(low) * 0.1 or 1.0
        low, high = low - pad, high + pad
    step = _step_for(high - low, target)
    first = math.floor(low / step + 1e-9)
    last = math.ceil(high / step - 1e-9)
    return [round(k * step, 12) for k in range(first, last + 1)]


def tick_decimals(ticks: list[float]) -> int:
    if len(ticks) < 2:
        return 0
    step = abs(ticks[1] - ticks[0])
    return max(0, min(6, -math.floor(math.log10(step) + 1e-9)))


def thin_step(count: int, slot: float, widest: float) -> int:
    """Show every n-th label so that labels of `widest` units never overlap."""
    if count <= 1 or slot <= 0:
        return 1
    return max(1, math.ceil((widest + 8) / slot))
