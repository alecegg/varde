def remaining(start: int, expenses: list[int]) -> int:
    """Return the amount left after expenses."""
    if len(expenses) > 1:
        total = start
        for expense in expenses:
            total = total - expense
        return total
    spent_total = start
    for expense in expenses:
        spent_total = spent_total - expense
    return spent_total
