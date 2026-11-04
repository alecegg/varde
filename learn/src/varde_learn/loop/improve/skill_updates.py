"""Pure parts of `skills updates`: the state of a synced skill and its diff.

States: `update-pending` (a newer packaged copy was recorded and not applied),
`loop-modified` (the tree is exactly what `accept` last wrote), `hand-modified`
(any other difference from the packaged copy) and `clean`.
"""

from __future__ import annotations

from collections.abc import Mapping

from varde_core import skill_props

from . import filediff

STATES = ("clean", "loop-modified", "hand-modified", "update-pending")


def classify(props: skill_props.Props, current_hash: str) -> str:
    if props.pending_hash:
        return "update-pending"
    if not skill_props.is_modified(props, current_hash):
        return "clean"
    if props.loop_hash and current_hash == props.loop_hash:
        return "loop-modified"
    return "hand-modified"


def diff_to_packaged(local: Mapping[str, str], packaged: Mapping[str, str]) -> str:
    """Unified diff turning the local files into the packaged files, by path."""
    parts = []
    for path in sorted(set(local) | set(packaged)):
        old, new = local.get(path), packaged.get(path, "")
        if old != new:
            parts.append(filediff.make_file_diff(path, old, new))
    return "".join(parts)
