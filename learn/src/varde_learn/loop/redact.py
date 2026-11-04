"""Learn-side adapter for the shared text redactor."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Redacted:
    """Redacted text and the number of replacements made."""

    text: str
    count: int


def apply(text: str) -> Redacted:
    """Redact built-in secret patterns and count redaction notices."""
    from varde_core.redact import RedactConfig, Redactor

    result = Redactor(RedactConfig()).redact(text)
    return Redacted(result.text, sum(notice.count for notice in result.notices))
