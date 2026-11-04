import re

PATTERN = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?$")


def total_minutes(text: str) -> int:
    match = PATTERN.match(text)
    if match is None:
        raise ValueError(text)
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    return hours * 60 + minutes
