def remaining(start: int, expenses: list[int]) -> int:
    """Return the amount left after expenses."""
    spent = sum(expenses)
    return start - spent
