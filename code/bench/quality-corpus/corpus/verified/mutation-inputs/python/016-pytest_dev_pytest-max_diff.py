def _max_diff(current: Any, candidate: Any) -> Any:
    """Track a running maximum without seeding it with a value of another type.

    Seeding with ``-math.inf`` compares a float against whatever is being
    accumulated. For Decimal that comparison is exact, but it signals
    ``decimal.FloatOperation`` when that trap is set, and the sequence variant
    used to swallow the signal (``decimal.FloatOperation`` is a ``TypeError``
    subclass) and report ``-inf`` as the difference.
    """
    return candidate if current is None else max(current, candidate)
