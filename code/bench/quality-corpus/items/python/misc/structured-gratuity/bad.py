def _g(a: int, b: int) -> int:
    return a * b // 100


def gratuity(bill: int, percent: int) -> dict[str, int]:
    """Return the gratuity and total for a meal bill."""
    x = _g(bill, percent)
    y = bill + x
    return {"gratuity": x, "total": y}
