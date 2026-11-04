"""Numeric and slicing expressions for the token audit fixture set."""

BITS = 0b1010_1010
MASK = 0xFF00
SCALE = 1.5e-3


def mix(value: int, shift: int) -> int:
    rotated = ((value << shift) | (value >> (32 - shift))) & MASK
    return rotated ^ BITS


def window(items: list[int], start: int, stop: int) -> list[int]:
    head = items[start:stop]
    tail = items[stop:]
    return head[::2] + tail[-3:]


def normalize(raw: float) -> float:
    scaled = raw * SCALE if raw > 0 else -raw
    return round(scaled, 6)


def flags(value: int) -> dict[str, bool]:
    return {
        "low": bool(value & 0x0F),
        "high": bool(value & 0xF0),
        "even": not (value % 2),
    }
