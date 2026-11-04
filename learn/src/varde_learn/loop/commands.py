"""Translate the grouped `varde learn` command path to the handler argument vectors."""

from __future__ import annotations

SESSION_VERBS = {"summary", "capture"}
SESSION_PASSTHROUGH = {"sweep": "sweep", "run": "run"}
INSPECT_OPTIONS = {"--session", "--snapshot-in", "--current", "--path"}
MEASURE_KINDS = {"trigger", "output", "calibrate"}


class CommandError(ValueError):
    """The grouped command path is not valid."""


def sessions_argv(args: list[str]) -> list[str]:
    """Map `sessions <verb> ...` to the handler argv (first item names it)."""
    if not args or args[0] in {"-h", "--help"}:
        return ["sessions", *args]
    verb, rest = args[0], args[1:]
    if verb in SESSION_VERBS:
        return ["diagnose", verb, *rest]
    if verb in SESSION_PASSTHROUGH:
        return [SESSION_PASSTHROUGH[verb], *rest]
    if verb == "calls":
        return ["calls", *rest]
    if verb == "fire":
        return ["guardrails", "fire", *rest]
    if verb == "show":
        return _show_argv(rest)
    raise CommandError(f"unexpected command `sessions {verb}`")


def _show_argv(rest: list[str]) -> list[str]:
    if rest and not rest[0].startswith("-"):
        return ["diagnose", "inspect", "--session", rest[0], *rest[1:]]
    if INSPECT_OPTIONS & set(rest):
        return ["diagnose", "inspect", *rest]
    return ["diagnose", "list", *rest]


def friction_argv(args: list[str]) -> list[str]:
    """Map `friction adopt|recurrence` to the adopt handler; others unchanged."""
    if args and args[0] == "adopt":
        return ["adopt", "record", *args[1:]]
    if args and args[0] == "recurrence":
        return ["adopt", "recurrence", *args[1:]]
    return ["friction", *args]


def measure_argv(args: list[str]) -> list[str]:
    """Map `measure <skill> <kind> ...` to `eval <kind> <skill> ...`."""
    if not args or args[0] in {"-h", "--help"}:
        return ["eval", *args[:0]]
    if len(args) < 2 or args[1] not in MEASURE_KINDS:
        raise CommandError(
            "usage: varde learn measure <skill> <trigger|output|calibrate> ..."
        )
    skill, kind, rest = args[0], args[1], args[2:]
    return ["eval", kind, skill, *rest]
