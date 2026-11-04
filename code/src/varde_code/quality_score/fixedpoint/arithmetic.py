"""Decimal-string conversion for integer micro-units."""

from decimal import Decimal, InvalidOperation

MICRO = 1_000_000


def from_decimal(value: str) -> int:
    """Convert an exact decimal string to micro-units."""
    try:
        scaled = Decimal(value) * MICRO
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc
    if not scaled.is_finite() or scaled != scaled.to_integral_value():
        raise ValueError("decimal value must have at most six fractional digits")
    return int(scaled)


def to_decimal(value: int, places: int = 6) -> str:
    """Format micro-units as a decimal string, rounding only for display."""
    if not 0 <= places <= 6:
        raise ValueError("places must be between zero and six")
    factor = 10 ** (6 - places)
    magnitude = abs(value)
    rounded = (magnitude + factor // 2) // factor
    whole, fraction = divmod(rounded, 10**places)
    sign = "-" if value < 0 else ""
    if places == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{fraction:0{places}d}"
