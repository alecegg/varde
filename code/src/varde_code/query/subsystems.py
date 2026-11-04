"""Name existing file communities as human-readable subsystems."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from varde_code.model import Community, RoleTag

from .noise_filter import is_generated_or_vendored_path, is_non_source_path

SUPERMAJORITY = 2 / 3
MIN_SUBSYSTEM_MEMBERS = 2


@dataclass(frozen=True)
class NamedCluster:
    id: int
    name: str
    members: list[str]


def name_clusters(
    clusters: list[Community], role_tags: dict[str, RoleTag]
) -> list[NamedCluster]:
    named: list[NamedCluster] = []
    for cluster in clusters:
        members = [
            path
            for path in cluster.members
            if not is_generated_or_vendored_path(path) and not is_non_source_path(path)
        ]
        if len(members) >= MIN_SUBSYSTEM_MEMBERS:
            named.append(NamedCluster(cluster.id, _name(members, role_tags), members))
    return _disambiguate(named)


def _name(members: list[str], role_tags: dict[str, RoleTag]) -> str:
    directories = [_parent(path) for path in members]
    counts = Counter(directories)
    directory, count = min(counts.items(), key=lambda item: (-item[1], item[0]))
    if count / len(members) >= SUPERMAJORITY:
        return _last_segment(directory) or "cluster"

    tags = Counter(role_tags[path] for path in members if path in role_tags)
    if tags:
        tag, count = min(tags.items(), key=lambda item: (-item[1], item[0].value))
        if count / len(members) >= SUPERMAJORITY:
            return f"{tag.value}s"

    directories = Counter(directory for directory in directories if directory)
    if directories:
        directory, _ = min(directories.items(), key=lambda item: (-item[1], item[0]))
        return _last_segment(directory) or "cluster"
    return "cluster"


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _last_segment(path: str) -> str | None:
    return path.rsplit("/", 1)[-1] if path else None


def _disambiguate(clusters: list[NamedCluster]) -> list[NamedCluster]:
    counts = Counter(cluster.name for cluster in clusters)
    result = [
        NamedCluster(
            cluster.id,
            f"{cluster.name}/{_representative_stem(cluster.members)}"
            if counts[cluster.name] > 1
            and _representative_stem(cluster.members)
            and _representative_stem(cluster.members) != cluster.name
            else cluster.name,
            cluster.members,
        )
        for cluster in clusters
    ]
    counts = Counter(cluster.name for cluster in result)
    return [
        NamedCluster(
            cluster.id,
            f"{cluster.name} #{cluster.id}"
            if counts[cluster.name] > 1
            else cluster.name,
            cluster.members,
        )
        for cluster in result
    ]


def _representative_stem(members: list[str]) -> str | None:
    if not members:
        return None
    filename = min(members).rsplit("/", 1)[-1]
    stem = filename.split(".", 1)[0]
    return stem or None
