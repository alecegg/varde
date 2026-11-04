"""Project registry supplied configuration choices into a JSON ready schema."""

from __future__ import annotations

from typing import Any

_CHOICE_FIELDS = ("harnesses", "models", "reasoning_efforts", "modes")


def config_choices(registry: Any) -> dict[str, dict[str, list[str]]]:
    """Return normalized per-harness choices supplied by the plugin registry."""
    harnesses = getattr(registry, "known_harnesses", None)
    if not callable(harnesses):
        return {}
    get_choices = getattr(registry, "config_choices", None)
    if not callable(get_choices):
        return {}

    registered = harnesses()
    if not isinstance(registered, (list, tuple, set, frozenset)):
        return {}
    result: dict[str, dict[str, list[str]]] = {}
    for harness in sorted(name for name in registered if isinstance(name, str)):
        try:
            supplied = get_choices(harness)
        except KeyError, LookupError, ValueError:
            continue
        if not isinstance(supplied, dict):
            continue
        result[harness] = {
            field: _strings(supplied.get(field)) for field in _CHOICE_FIELDS
        }
    return result


def _strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    return list(dict.fromkeys(item for item in value if isinstance(item, str)))
