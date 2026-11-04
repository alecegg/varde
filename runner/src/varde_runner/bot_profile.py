"""Generic restricted launch profile for the manager bot (pure, no I/O).

The runner defines the profile; an adapter maps it to its own flags and refuses
a restricted launch when it cannot. Nothing here names a harness.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

BOT_ROLE = "manager-bot"
PROFILE_RESTRICTED = "restricted"
BOT_TOKEN_ENV = "VARDE_BOT_TOKEN"  # noqa: S105 - a variable name, not a secret

# Small allowlist: enough for a CLI to find the user's own login and run, nothing else.
ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "TERM",
    "TMPDIR",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "XDG_CACHE_HOME",
)
_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9._:/-]{1,200}")


class ProfileUnsupported(RuntimeError):
    """The harness cannot enforce the restricted profile, so the launch is refused."""


@dataclass(frozen=True, slots=True)
class RestrictedProfile:
    """What a restricted session may use. Tool kinds are generic; adapters name them."""

    file_tools: tuple[str, ...] = ("read", "search", "list")
    shell_tool: str = "shell"  # every call still passes the argv allowlist hook
    network_tools: tuple[str, ...] = ()
    user_settings: bool = False
    extra_dirs: bool = False
    mode: str = "bot"  # runner mode: every tool request reaches the host

    @property
    def tool_kinds(self) -> tuple[str, ...]:
        return (*self.file_tools, self.shell_tool)


def restricted_profile() -> RestrictedProfile:
    return RestrictedProfile()


def is_restricted(profile: str | None) -> bool:
    return profile == PROFILE_RESTRICTED


def profile_for_role(role: str) -> str | None:
    """The bot role always launches restricted; no other role does."""
    return PROFILE_RESTRICTED if role == BOT_ROLE else None


def check_restricted_overlay(overlay: Mapping[str, str]) -> None:
    """A restricted session may be given the bot token and nothing else.

    Any other key (PATH, LD_*, provider keys, identity) or a malformed token raises
    ``ValueError``; the launch or resume then fails closed.
    """
    extra = sorted(set(overlay) - {BOT_TOKEN_ENV})
    if extra:
        raise ValueError(f"restricted sessions accept only {BOT_TOKEN_ENV}: {extra}")
    if BOT_TOKEN_ENV in overlay and not valid_token(overlay[BOT_TOKEN_ENV]):
        raise ValueError("bot token is malformed")


def restricted_environment(
    source: Mapping[str, str], overlay: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Allowlisted variables from ``source`` plus the bot token overlay.

    Everything else is dropped, including provider keys and ambient identity.
    """
    check_restricted_overlay(overlay or {})
    env = {key: source[key] for key in ENV_ALLOWLIST if key in source}
    env.update(overlay or {})
    return env


def valid_token(value: object) -> bool:
    return isinstance(value, str) and _TOKEN_SHAPE.fullmatch(value) is not None
