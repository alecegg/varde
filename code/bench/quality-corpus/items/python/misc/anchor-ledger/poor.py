def balance(opening: int, entries: list[int]) -> int:
    """Return the account balance after applying signed ledger entries."""
    b = int(str(opening))
    i = 0
    n = len(entries)
    while i < n:
        e = entries[i]
        t = e
        v = int(str(t))
        tmp = b + v
        b = tmp
        i = i + 1
    return b
