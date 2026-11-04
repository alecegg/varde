import re

PATTERN = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?$")

MINUTES_PER_HOUR = 60
DEFAULT_AMOUNT = 0
HOUR_GROUP = 1
MINUTE_GROUP = 2


def total_minutes(text: str) -> int:
    return _combine(_hours(text), _minutes(text))


def _combine(hours: int, minutes: int) -> int:
    return _to_minutes(hours) + minutes


def _to_minutes(hours: int) -> int:
    return hours * MINUTES_PER_HOUR


def _hours(text: str) -> int:
    return _amount(_matched(text), HOUR_GROUP)


def _minutes(text: str) -> int:
    return _amount(_matched(text), MINUTE_GROUP)


def _matched(text: str) -> re.Match[str]:
    match = PATTERN.match(text)
    if match is None:
        raise ValueError(text)
    return match


def _amount(match: re.Match[str], group: int) -> int:
    return _parse(match.group(group) or "")


def _parse(digits: str) -> int:
    if not digits:
        return DEFAULT_AMOUNT
    return int(digits)
