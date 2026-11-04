"""In-memory resolved graph and Python-format serialization.

Published signatures: ``Graph(paths, out, inc)``, ``to_dict() -> dict`` and
``from_dict(value: Mapping[str, object]) -> Graph``. ``paths`` maps file IDs
to paths; ``out`` and ``inc`` map file IDs to adjacent IDs. Serialization
uses JSON-compatible string keys and integer adjacency lists; postcard
decoding is intentionally left to SQL fallback in the Rust fixture reader.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass
class Graph:
    paths: dict[int, str] = field(default_factory=dict)
    out: dict[int, list[int]] = field(default_factory=dict)
    inc: dict[int, list[int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, dict[str, object]]:
        return {
            "paths": {str(key): value for key, value in self.paths.items()},
            "out": {str(key): value for key, value in self.out.items()},
            "inc": {str(key): value for key, value in self.inc.items()},
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Graph:
        return cls(
            paths={
                int(key): str(path) for key, path in _mapping(value, "paths").items()
            },
            out={
                int(key): [int(item) for item in ids]
                for key, ids in _mapping(value, "out").items()
                if isinstance(ids, (list, tuple))
            },
            inc={
                int(key): [int(item) for item in ids]
                for key, ids in _mapping(value, "inc").items()
                if isinstance(ids, (list, tuple))
            },
        )


def _mapping(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    result = value.get(key)
    if not isinstance(result, Mapping):
        raise ValueError(f"graph field {key!r} must be an object")
    return result
