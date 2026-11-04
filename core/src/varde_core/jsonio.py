"""Compact and pretty JSON output with serde_json-compatible formatting."""

import json
import math
from decimal import Decimal


def _float(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("non-finite floats are not valid JSON")
    text = repr(value)
    if "e" in text or "E" in text:
        mantissa, exponent = text.lower().split("e")
        if int(exponent) == -5:
            return format(Decimal(text), "f")
        sign = "-" if int(exponent) < 0 else ""
        text = f"{mantissa}e{sign}{abs(int(exponent))}"
    return text


def _encode(value: object, *, pretty: bool, depth: int = 0) -> str:
    if value is None or isinstance(value, (bool, int, str)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, float):
        return _float(value)
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        items = [_encode(item, pretty=pretty, depth=depth + 1) for item in value]
        if not pretty:
            return "[" + ",".join(items) + "]"
        pad, child = "  " * depth, "  " * (depth + 1)
        return "[\n" + child + (",\n" + child).join(items) + "\n" + pad + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            encoded_key = json.dumps(key, ensure_ascii=False)
            separator = ": " if pretty else ":"
            items.append(
                encoded_key + separator + _encode(item, pretty=pretty, depth=depth + 1)
            )
        if not pretty:
            return "{" + ",".join(items) + "}"
        pad, child = "  " * depth, "  " * (depth + 1)
        return "{\n" + child + (",\n" + child).join(items) + "\n" + pad + "}"
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def dumps(value: object) -> str:
    return _encode(value, pretty=False)


def dumps_pretty(value: object) -> str:
    return _encode(value, pretty=True)
