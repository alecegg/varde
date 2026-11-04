"""Small typed-field helpers shared by the block schemas. Pure functions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Fault:
    rule: str
    message: str


def type_name(value: object) -> str:
    return type(value).__name__


def is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def check_keys(
    data: dict[str, object],
    required: set[str],
    optional: set[str],
    where: str,
) -> list[Fault]:
    faults = [
        Fault("missing-key", f"{where}: missing required key '{key}'")
        for key in sorted(required - data.keys())
    ]
    faults += [
        Fault("unknown-key", f"{where}: unknown key '{key}'")
        for key in sorted(data.keys() - required - optional)
    ]
    return faults


def str_field(data: dict[str, object], key: str, where: str) -> list[Fault]:
    """Fault unless key is absent (caller reports) or a non-empty string."""
    if key not in data:
        return []
    value = data[key]
    if isinstance(value, str) and value.strip():
        return []
    return [Fault("type", f"{where}: '{key}' must be a non-empty string")]


def str_map(value: object, where: str) -> list[Fault]:
    if not isinstance(value, dict) or not value:
        return [Fault("type", f"{where} must be a non-empty table of strings")]
    bad = sorted(k for k, v in value.items() if not isinstance(v, str))
    return [Fault("type", f"{where}.{k} must be a string") for k in bad]


def list_of(value: object, where: str, kind: type = str) -> list[Fault]:
    if not isinstance(value, list) or not value:
        return [Fault("type", f"{where} must be a non-empty list of {kind.__name__}")]
    if all(isinstance(item, kind) for item in value):
        return []
    return [Fault("type", f"{where} must contain only {kind.__name__} values")]


def tables(data: dict[str, object], key: str, where: str) -> list[dict[str, object]]:
    """Return data[key] when it is a list of tables, else an empty list."""
    value = data.get(key)
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return list(value)
    return []


def tables_fault(data: dict[str, object], key: str, where: str) -> list[Fault]:
    value = data.get(key)
    if key not in data:
        return []
    if isinstance(value, list) and value and all(isinstance(i, dict) for i in value):
        return []
    return [Fault("type", f"{where}: '{key}' must be a non-empty array of tables")]


def duplicates(names: list[str]) -> list[str]:
    seen: set[str] = set()
    repeated: list[str] = []
    for name in names:
        if name in seen and name not in repeated:
            repeated.append(name)
        seen.add(name)
    return repeated
