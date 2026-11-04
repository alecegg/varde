def _integer_amount(value: object) -> int:
    if not isinstance(value, int):
        raise TypeError("ledger values must be integers")
    return value


def balance(opening: int, entries: list[int]) -> int:
    """Return the account balance after applying signed ledger entries."""
    return _integer_amount(opening) + sum(_integer_amount(entry) for entry in entries)
