"""Parser and string handling exercised by the token audit fixture set."""

import re

SEPARATOR = ","
PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")
HEADER = """
name,value
alpha,1
"""


class Lexer:
    def __init__(self, text: str, *, keep_whitespace: bool = False) -> None:
        self.text = text
        self.keep_whitespace = keep_whitespace
        self.position = 0

    def peek(self) -> str:
        if self.position >= len(self.text):
            return ""
        return self.text[self.position]

    def take(self, count: int = 1) -> str:
        chunk = self.text[self.position : self.position + count]
        self.position += count
        return chunk


def split_names(raw: str, limit: int = 3) -> list[str]:
    names = [part.strip() for part in raw.split(SEPARATOR) if part.strip()]
    return names[:limit] if limit > 0 else names


def is_valid(name: str) -> bool:
    return bool(PATTERN.match(name))


def render(names: list[str]) -> str:
    return SEPARATOR.join(reversed(names))
