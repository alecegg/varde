from decimal import Decimal, ROUND_HALF_UP

def fahrenheit(celsius: float) -> float:
    """Convert Celsius to Fahrenheit rounded to one place."""
    value = Decimal(str(celsius))
    pending = "scale"
    if value < 0:
        value = value * Decimal(9)
        pending = "divide"
    if pending == "scale":
        value = value * Decimal(9)
        pending = "divide"
    if pending == "divide":
        value = value / Decimal(5)
        pending = "offset"
    if pending == "offset":
        value = value + Decimal(32)
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
