"""Import and call resolution for extracted entity JSON."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

from varde_code.model import Community, EdgeKind, EntityKind
from varde_code.parse import language_for_path

from .aux import Edge, FileNode, detect_communities, integer_value
from .calls import resolve_calls
from .imports import resolve_import_targets


def resolve(
    entities: Sequence[Mapping[str, Any]],
    symbols: Sequence[Mapping[str, Any]],
    files: Sequence[str],
) -> dict[str, Any]:
    """Resolve imports and calls from extractor JSON into graph records.

    Symbol spans preserve import bindings omitted from Python import entities.
    """
    normalized_entities = [_entity(entity) for entity in entities]
    file_index = _FileIndex(files)
    imports = _resolve_imports(normalized_entities, file_index)
    edges = imports + resolve_calls(normalized_entities, imports, files, symbols)
    from .hierarchy import resolve_hierarchy

    edges.extend(resolve_hierarchy(normalized_entities))
    nodes, communities = _build_nodes_and_communities(normalized_entities, files, edges)
    return {
        "nodes": nodes,
        "edges": edges,
        "communities": [
            {"id": community.id, "members": community.members}
            for community in communities
        ],
        "clone_bands": [],
    }


def _entity(value: Mapping[str, Any]) -> dict[str, Any]:
    kind_value = value.get("kind")
    if isinstance(kind_value, str):
        try:
            kind = EntityKind[kind_value.upper()]
        except KeyError as exc:
            raise ValueError(f"unknown entity kind: {kind_value}") from exc
    elif isinstance(kind_value, int):
        kind = EntityKind.from_i64(kind_value)
        if kind is None:
            raise ValueError(f"unknown entity kind: {kind_value}")
    else:
        raise ValueError("entity kind must be a string or integer")

    file_id = value.get("file_id")
    name = value.get("name")
    if not isinstance(file_id, int) or not isinstance(name, str):
        raise ValueError("entity file_id must be an integer and name must be a string")
    return {**value, "kind": kind, "file_id": file_id, "name": name}


class _FileIndex:
    """Per-resolution path and language indexes for import matching."""

    def __init__(self, files: Sequence[str]) -> None:
        self.files = files
        self.paths: list[PurePosixPath] = []
        self.languages: list[str | None] = []
        self.parts: list[tuple[str, ...] | None] = []
        self.suffixless_parts: list[tuple[str, ...] | None] = []
        self.stems: dict[str, list[int]] = defaultdict(list)
        self._parts: dict[int, dict[tuple[str, ...], list[int]]] = {}
        self._suffixless_parts: dict[int, dict[tuple[str, ...], list[int]]] = {}
        self.normalized_paths: dict[PurePosixPath, list[int]] = defaultdict(list)
        self.paths_without_suffix: dict[PurePosixPath, list[int]] = defaultdict(list)
        self.init_parents: dict[PurePosixPath, list[int]] = defaultdict(list)

        for index, value in enumerate(files):
            path = PurePosixPath(value)
            language = language_for_path(str(path))
            self.paths.append(path)
            self.languages.append(language)
            self.parts.append(path.parts if language is not None else None)
            self.suffixless_parts.append(
                path.with_suffix("").parts if language is not None else None
            )
            if language is None:
                continue
            self.stems[path.stem].append(index)
            self.normalized_paths[path].append(index)
            self.paths_without_suffix[path.with_suffix("")].append(index)
            if path.stem == "__init__":
                self.init_parents[path.parent].append(index)

    def trailing_parts(
        self, count: int, *, suffixless: bool = False
    ) -> dict[tuple[str, ...], list[int]]:
        indexes = self._suffixless_parts if suffixless else self._parts
        if count not in indexes:
            grouped: dict[tuple[str, ...], list[int]] = defaultdict(list)
            parts_by_file = self.suffixless_parts if suffixless else self.parts
            for index, parts in enumerate(parts_by_file):
                if parts is None:
                    continue
                grouped[parts[-count:]].append(index)
            indexes[count] = grouped
        return indexes[count]


def _resolve_imports(
    entities: Sequence[Mapping[str, object]], file_index: _FileIndex
) -> list[dict[str, object]]:
    return [
        _edge(file_id, EdgeKind.IMPORT, entity_id, target, "file")
        for file_id, entity_id, target in resolve_import_targets(
            entities, file_index.files
        )
    ]


def _match_import(specifier: str, from_file: int, file_index: _FileIndex) -> int | None:
    if not 0 <= from_file < len(file_index.files):
        return None
    source = file_index.paths[from_file]
    source_language = file_index.languages[from_file]
    if source_language is None:
        return None
    spec = specifier.strip().strip("\\\"'").replace("\\", "/")
    candidates: set[int] = set()

    if spec.startswith("."):
        dot_count = len(spec) - len(spec.lstrip("."))
        suffix = spec[dot_count:].lstrip("./")
        base = source.parent
        for _ in range(max(dot_count - 1, 0)):
            base = base.parent
        normalized = PurePosixPath(_normalize_path(str(base / suffix)))
        candidates.update(file_index.normalized_paths.get(normalized, ()))
        candidates.update(file_index.paths_without_suffix.get(normalized, ()))
        candidates.update(file_index.init_parents.get(normalized, ()))
    else:
        path_spec = spec.replace(".", "/")
        segments = [part for part in path_spec.split("/") if part]
        if segments:
            candidates.update(file_index.stems.get(segments[-1], ()))
            candidates.update(
                file_index.trailing_parts(len(segments)).get(tuple(segments), ())
            )
            candidates.update(
                file_index.trailing_parts(len(segments), suffixless=True).get(
                    tuple(segments), ()
                )
            )

    valid = [
        index for index in candidates if file_index.languages[index] == source_language
    ]
    return valid[0] if len(valid) == 1 else None


def _edge(
    from_file: int,
    kind: EdgeKind,
    entity_id: int,
    target_id: int | None,
    target_type: str,
) -> dict[str, object]:
    target = {"target": "unknown"}
    if target_id is not None:
        target = {"target": target_type, "id": target_id}
    return {
        "from": from_file,
        "to": target,
        "kind": kind.as_str(),
        "resolved": target_id is not None,
        "from_entity": entity_id,
    }


def _build_nodes_and_communities(
    entities: Sequence[Mapping[str, object]],
    files: Sequence[str],
    edges: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], list[Community]]:
    fan_in = [0] * len(files)
    fan_out = [0] * len(files)
    community_edges = []
    for edge in edges:
        if not edge["resolved"]:
            continue
        source = integer_value(edge["from"])
        target = edge["to"]
        if not isinstance(target, Mapping):
            continue
        target_file = integer_value(target["id"])
        target_entity = None
        if target["target"] == "entity":
            target_entity = target_file
            target_file = integer_value(entities[target_file]["file_id"])
        fan_out[source] += 1
        fan_in[target_file] += 1
        community_edges.append(
            Edge(from_file=source, to_file=target_file, to_entity=target_entity)
        )

    file_nodes = [FileNode(path) for path in files]
    communities = detect_communities(file_nodes, community_edges, list(entities))
    nodes = [
        {
            "path": path,
            "community_id": file_nodes[index].community_id,
            "fan_in": fan_in[index],
            "fan_out": fan_out[index],
        }
        for index, path in enumerate(files)
    ]
    return nodes, communities


def _normalize_path(path: str) -> str:
    absolute = path.startswith("/")
    parts: list[str] = []
    for part in path.split("/"):
        if part in {"", "."}:
            continue
        if part == ".." and parts:
            parts.pop()
        else:
            parts.append(part)
    normalized = "/".join(parts)
    return f"/{normalized}" if absolute else normalized
