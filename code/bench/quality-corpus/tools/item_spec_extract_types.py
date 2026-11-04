from __future__ import annotations

import re
from dataclasses import dataclass

TOKEN = re.compile(r"\w+|[^\w\s]")
ANONYMOUS = "<anonymous>"


class SourceSyntaxError(ValueError):
    """Raised when a source file cannot be parsed by its language grammar."""


@dataclass
class Function:
    name: str
    tokens: int
    lines: int
    calls: list[str]
    complexity: int
    signature: str
    edges: list[str] | None = None
