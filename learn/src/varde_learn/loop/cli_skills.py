"""`varde learn skills <verb>`: skill demand and the self-improvement loop."""

from __future__ import annotations

import importlib
import sys

from .help import help_text

# verb -> module; a verb whose module does not exist yet exits 2.
VERB_MODULES = {
    "demand": "cli_how_report",
    "candidates": "cli_skills_candidates",
    "extract": "cli_skills_extract",
    "reset": "cli_skills_reset",
    "accept": "cli_skills_accept",
    "fill": "cli_skills_fill",
    "reject": "cli_skills_reject",
    "report": "cli_skills_report",
    "updates": "cli_skills_updates",
}


def run(args: list[str], io: object | None = None) -> int:
    if not args or args[0] in {"-h", "--help"}:
        _write(io, help_text("skills"))
        return 0
    verb, rest = args[0], args[1:]
    if verb not in VERB_MODULES:
        _write(io, f"error: unknown skills command '{verb}'\n", error=True)
        return 2
    if verb != "demand" and any(arg in {"-h", "--help"} for arg in rest):
        _write(io, help_text(f"skills {verb}"))
        return 0
    module = _load(VERB_MODULES[verb])
    if module is None:
        _write(io, f"error: skills {verb}: not yet available\n", error=True)
        return 2
    return module.run(rest, io)


def _load(name: str):
    try:
        return importlib.import_module(f"{__package__}.{name}")
    except ModuleNotFoundError as error:
        if error.name != f"{__package__}.{name}":
            raise
        return None


def _write(io: object | None, text: str, *, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    print(text, end="", file=stream or (sys.stderr if error else sys.stdout))
