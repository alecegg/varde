"""Translate `varde learn knowledge <verb>` and `varde setup paths` to handler argv."""

from __future__ import annotations

CONCEPT_VERBS = {"create", "show", "update", "set-field", "delete"}
FILTER_OPTIONS = {"--field", "--text"}


ALIAS_VERBS = CONCEPT_VERBS | {"search", "lint", "map"}
NEW_VERB = {"create": "add"}


def deprecation_notice(verb: str) -> str:
    """The stderr line for a `knowledge <verb>` alias; empty when it has none."""
    if verb == "paths":
        replacement = "varde setup paths"
    elif verb in ALIAS_VERBS:
        replacement = f"varde learn memory {NEW_VERB.get(verb, verb)}"
    else:
        return ""
    return (
        f"notice: `varde learn knowledge {verb}` is deprecated and will be removed "
        f"in the next release; use `{replacement}`"
    )


class CommandError(ValueError):
    """The grouped command path is not valid."""


def _is_filtered(args: list[str]) -> bool:
    return any(arg in FILTER_OPTIONS or arg.startswith("--field=") for arg in args)


def knowledge_argv(args: list[str]) -> list[str]:
    """Map `knowledge <verb> ...` to the handler argv (`concept ...` or `lint ...`)."""
    if not args:
        raise CommandError(
            "usage: varde learn knowledge "
            "<create|show|update|set-field|delete|search|map|lint>"
        )
    verb, rest = args[0], args[1:]
    if verb in CONCEPT_VERBS:
        return ["concept", verb, *rest]
    if verb == "search":
        return ["concept", "search" if _is_filtered(rest) else "list", *rest]
    if verb in {"lint", "map"}:
        return [verb, *rest]
    raise CommandError(f"unexpected command `knowledge {verb}`")
