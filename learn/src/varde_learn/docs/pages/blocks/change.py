"""The shared change vocabulary: `change` and `was` on a row, field or entity."""

from varde_learn.docs.pages.blocks.rules import Fault

CHANGES = ("added", "modified", "removed", "renamed")
_ALLOWED = ", ".join(CHANGES)
CHANGE_FIELDS = (
    "change  optional: added, modified, removed or renamed",
    "was     optional previous name, type or value; required for renamed only",
)


def change_faults(data: dict[str, object], where: str) -> list[Fault]:
    """Faults for the optional `change` and `was` keys of one table."""
    faults: list[Fault] = []
    change = data.get("change")
    has_was = "was" in data
    if "change" in data and change not in CHANGES:
        faults.append(Fault("change", f"{where}: change must be one of {_ALLOWED}"))
    was = data.get("was")
    if has_was and not (isinstance(was, str) and was.strip()):
        faults.append(Fault("type", f"{where}: 'was' must be a non-empty string"))
    if has_was and "change" not in data:
        faults.append(Fault("change", f"{where}: was needs a change ({_ALLOWED})"))
    if change == "renamed" and not has_was:
        faults.append(
            Fault("change", f"{where}: renamed needs was (the previous name)")
        )
    if change in ("added", "removed") and has_was:
        faults.append(Fault("change", f"{where}: {change} cannot have was"))
    return faults
