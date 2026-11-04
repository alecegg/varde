"""Embedded hook plugin templates installed for supported harnesses."""

from importlib.resources import files

_HOOK_ASSETS = frozenset({"opencode.ts", "opencode-v1.ts", "pi.ts"})


def load_hook_asset(name: str) -> bytes:
    """Return the bytes for a bundled hook plugin template."""
    if name not in _HOOK_ASSETS:
        raise ValueError(f"unknown hook asset: {name}")
    return files(__package__).joinpath(name).read_bytes()
