"""Argument parsing for the design subcommands. Pure."""

from __future__ import annotations

from dataclasses import dataclass, field

from .registry import PROFILES


class UsageError(ValueError):
    """Raised for an unknown flag or a missing or bad flag value."""


@dataclass
class Options:
    paths: list[str] = field(default_factory=list)
    json: bool = False
    static_only: bool = False
    profile: str | None = None
    config: str | None = None
    tokens: str | None = None
    widths: tuple[int, ...] | None = None


_VALUE_FLAGS = {
    "check": ("--profile", "--config", "--tokens", "--width"),
    "tokens": ("--config",),
    "survey": (),
}
_SWITCHES = {
    "check": ("--json", "--static-only"),
    "tokens": ("--json",),
    "survey": ("--json",),
}


def _widths(text: str) -> tuple[int, ...]:
    try:
        values = tuple(int(part) for part in text.split(","))
    except ValueError as error:
        message = f"--width: expected integers such as 390,768, got {text!r}"
        raise UsageError(message) from error
    if not values or any(v <= 0 for v in values):
        raise UsageError(f"--width: expected positive integers, got {text!r}")
    return values


def _set_value(options: Options, flag: str, value: str) -> None:
    if flag == "--profile" and value not in PROFILES:
        raise UsageError(f"--profile: expected one of {', '.join(PROFILES)}")
    if flag == "--width":
        options.widths = _widths(value)
    else:
        setattr(options, flag[2:], value)


def parse_options(command: str, argv: list[str]) -> Options:
    """Options for command; flags may appear anywhere, other words are paths."""
    options = Options()
    index = 0
    while index < len(argv):
        word = argv[index]
        index += 1
        if word in _SWITCHES[command]:
            setattr(options, word[2:].replace("-", "_"), True)
        elif word in _VALUE_FLAGS[command]:
            if index >= len(argv):
                raise UsageError(f"{word} needs a value")
            _set_value(options, word, argv[index])
            index += 1
        elif word.startswith("-") and word != "-":
            raise UsageError(f"unknown option for {command}: {word}")
        else:
            options.paths.append(word)
    return options
