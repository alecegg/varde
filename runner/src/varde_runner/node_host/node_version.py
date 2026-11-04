"""Node version gate."""

from __future__ import annotations

MIN_NODE = (22, 19)


def node_version_supported(version: str) -> bool:
    try:
        major, minor = (int(part) for part in version.split(".")[:2])
    except ValueError:
        return False
    return (major, minor) >= MIN_NODE
