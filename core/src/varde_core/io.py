"""Optional capabilities passed by the app to a module."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Io:
    impact: object | None = None
    capture: object | None = None
