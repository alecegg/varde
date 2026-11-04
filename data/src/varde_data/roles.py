"""Shared role names and address recognition."""

ROLES = frozenset(
    {"manager", "orchestrator", "planner", "builder", "reviewer", "explorer", "guard"}
)


def role_for_address(address: str) -> str | None:
    """Return the role represented by a role address or canonical role slot."""
    if address == "main":
        return "manager"
    if (
        address.startswith("orchestrator-")
        and address.removeprefix("orchestrator-").isdecimal()
    ):
        return "orchestrator"
    role, separator, _qualifier = address.partition(":")
    if separator and role in ROLES:
        return role
    return next(
        (role for role in ROLES if address.endswith(f"-{role}")),
        None,
    )
