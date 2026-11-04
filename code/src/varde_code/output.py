"""Output capture capability types used by varde-code."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CaptureInput:
    """Text or item list to capture."""

    text: str | None = None
    items: tuple[str, ...] | None = None

    @classmethod
    def from_text(cls, text: str) -> CaptureInput:
        return cls(text=text)

    @classmethod
    def from_items(cls, items: list[str] | tuple[str, ...]) -> CaptureInput:
        return cls(items=tuple(items))


class OutputCapture(Protocol):
    def capture(self, input: CaptureInput, source: str, label: str) -> str | None: ...
