"""Varde-wide configuration and platform data directories."""

import os
import sys
from pathlib import Path


def _nonempty_env(name: str) -> str | None:
    value = os.environ.get(name)
    return value or None


def _home_dir() -> Path | None:
    home = _nonempty_env("HOME")
    if home is not None:
        return Path(home)
    try:
        return Path.home()
    except RuntimeError:
        return None


def varde_config_dir() -> Path:
    configured = _nonempty_env("VARDE_CONFIG_DIR")
    if configured is not None:
        return Path(configured)
    xdg = _nonempty_env("XDG_CONFIG_HOME")
    if xdg is not None:
        return Path(xdg) / "varde"
    home = _home_dir()
    return (home / ".config" if home is not None else Path(".config")) / "varde"


def data_dir() -> Path | None:
    home = _home_dir()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" if home is not None else None
    xdg = _nonempty_env("XDG_DATA_HOME")
    if xdg is not None and Path(xdg).is_absolute():
        return Path(xdg)
    return home / ".local" / "share" if home is not None else None


def local_share_dir() -> Path:
    """Return $XDG_DATA_HOME if absolute, else ~/.local/share, on every platform."""
    xdg = _nonempty_env("XDG_DATA_HOME")
    if xdg is not None and Path(xdg).is_absolute():
        return Path(xdg)
    home = _home_dir()
    return (home if home is not None else Path("/")) / ".local" / "share"


def fnv1a64(contents: bytes) -> int:
    """Return the unsigned FNV-1a 64-bit hash of bytes."""
    value = 0xCBF29CE484222325
    for byte in contents:
        value = ((value ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return value
