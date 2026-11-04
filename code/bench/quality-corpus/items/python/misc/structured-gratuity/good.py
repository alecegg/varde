def gratuity(bill: int, percent: int) -> dict[str, int]:
    """Return the gratuity and total for a meal bill."""
    gratuity_amount = bill * percent // 100
    return {"gratuity": gratuity_amount, "total": bill + gratuity_amount}
