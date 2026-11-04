from decimal import Decimal, ROUND_HALF_UP

def fahrenheit(celsius: float) -> float:
    """Convert Celsius to Fahrenheit rounded to one place."""
    value = Decimal(str(celsius)) * Decimal(9) / Decimal(5) + Decimal(32)
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
