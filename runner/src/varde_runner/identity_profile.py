"""Pure identity profile defaults, parsing, rendering, and validation."""

from __future__ import annotations

import json
import tomllib
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from varde_runner.config import ROLE_NAMES

ROLE_DESCRIPTIONS = {
    "orchestrator": "Runs a plan and hands work to the other roles.",
    "planner": "Shapes a plan before any code is written.",
    "builder": "Implements one task at a time.",
    "explorer": "Reads the code and reports what it finds.",
    "reviewer": "Checks finished work against the plan.",
    "judge": "Settles disagreements between reviews.",
    "manager-bot": "Delegates work to other agents within the user's limits.",
    "guard": (
        "First pass on permission prompts; approves only allowlisted patterns, "
        "escalates the rest."
    ),
}
PROFILE_IDS = frozenset((*ROLE_NAMES, "manager"))


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    label: str
    description: str
    role: str


class ProfileError(ValueError):
    """A profile document is malformed or invalid."""


def defaults(role_names: tuple[str, ...] = ROLE_NAMES) -> dict[str, Profile]:
    """Return built-in profiles for each configured role and the manager."""
    profiles = {
        role: Profile(
            id=role,
            name=role.title(),
            label=role,
            description=ROLE_DESCRIPTIONS[role],
            role=role,
        )
        for role in role_names
    }
    profiles["manager"] = Profile(
        id="manager",
        name="Manager",
        label="manager",
        description="Coordinates work across the agent team.",
        role="manager",
    )
    return profiles


def validate(
    fields: Mapping[str, object], file_stem: str | None = None
) -> dict[str, str]:
    """Return field-specific validation messages for profile fields."""
    errors: dict[str, str] = {}
    name, label, description, role = (
        fields.get("name"),
        fields.get("label"),
        fields.get("description"),
        fields.get("role"),
    )
    if not _valid_text(name, 1, 40, allow_blank=False):
        errors["name"] = "name must be 1 to 40 characters"
    if not _valid_text(label, 1, 24, allow_blank=False):
        errors["label"] = "label must be 1 to 24 characters"
    if not _valid_text(description, 0, 280):
        errors["description"] = "description must be at most 280 characters"
    expected_id = file_stem if file_stem is not None else role
    if not isinstance(expected_id, str) or expected_id not in PROFILE_IDS:
        errors["role"] = "unknown identity"
    elif role != expected_id:
        errors["role"] = "role must match identity id"
    return errors


def _valid_text(
    value: object, minimum: int, maximum: int, *, allow_blank: bool = True
) -> bool:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        return False
    if not allow_blank and not value.strip():
        return False
    return not any(unicodedata.category(char) in {"Cc", "Cs"} for char in value)


def parse(text: str, file_stem: str | None = None) -> Profile:
    """Parse one profile TOML document, raising ProfileError if it is invalid."""
    try:
        fields = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"invalid TOML: {exc}") from exc
    errors = validate(fields, file_stem)
    if errors:
        messages = "; ".join(f"{field}: {message}" for field, message in errors.items())
        raise ProfileError(messages)
    identity_id = file_stem if file_stem is not None else fields["role"]
    return Profile(
        id=identity_id,
        name=fields["name"],
        label=fields["label"],
        description=fields["description"],
        role=fields["role"],
    )


def render(profile: Profile) -> str:
    """Render profile fields as valid UTF-8 TOML text."""
    return (
        "\n".join(
            f"{key} = {json.dumps(value, ensure_ascii=False)}"
            for key, value in (
                ("name", profile.name),
                ("label", profile.label),
                ("description", profile.description),
                ("role", profile.role),
            )
        )
        + "\n"
    )
