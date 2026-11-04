"""Deterministic workflow dependency graph and readiness resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_learn.knowledge.frontmatter import parse

from varde_workflow.schema import SCHEMA_VERSION, WorkflowSchema


@dataclass(frozen=True, order=True)
class Blocker:
    code: str
    artifact_id: str
    dependency: str
    status: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "artifact_id": self.artifact_id,
            "dependency": self.dependency,
            "status": self.status,
        }


@dataclass
class WorkflowArtifact:
    id: str
    artifact_type: str
    status: str
    depends_on: list[str]
    path: Path


@dataclass
class ArtifactGraph:
    root_id: str
    nodes: dict[str, WorkflowArtifact]
    blockers: list[Blocker]

    @classmethod
    def resolve(cls, path: Path | str, schema: WorkflowSchema) -> ArtifactGraph:
        root = read_artifact(Path(path), schema)
        graph = cls(root.id, {}, [])
        graph._visit(root, schema, set())
        graph._add_completion_blockers(schema)
        graph.blockers = sorted(set(graph.blockers))
        return graph

    def root(self) -> WorkflowArtifact:
        return self.nodes[self.root_id]

    def root_blockers(self) -> list[Blocker]:
        return [item for item in self.blockers if item.artifact_id == self.root_id]

    def actions(self, schema: WorkflowSchema) -> list[str]:
        root = self.root()
        actions = sorted(
            schema.artifact_type(root.artifact_type).transitions.get(root.status, set())
        )
        if self.root_blockers():
            actions = [action for action in actions if action == "blocked"]
        return actions

    def to_json(self, schema: WorkflowSchema) -> dict[str, Any]:
        nodes = [
            {
                "id": node.id,
                "artifact_type": node.artifact_type,
                "status": node.status,
                "path": str(node.path),
            }
            for node in sorted(self.nodes.values(), key=lambda item: item.id)
        ]
        edges = [
            {
                "from": node.id,
                "to": self._resolved_id(dependency) or dependency,
                "relationship": "depends_on",
            }
            for node in self.nodes.values()
            for dependency in node.depends_on
        ]
        edges.sort(key=_json_sort_key)
        return {
            "schema": schema.to_json(),
            "root_id": self.root_id,
            "nodes": nodes,
            "edges": edges,
            "blockers": [item.to_json() for item in self.blockers],
        }

    def readiness_json(self, schema: WorkflowSchema) -> dict[str, Any]:
        blockers = self.root_blockers()
        return {
            "schema_version": SCHEMA_VERSION,
            "artifact_id": self.root_id,
            "ready": not blockers,
            "blockers": [item.to_json() for item in blockers],
            "actions": self.actions(schema),
        }

    def _visit(
        self, artifact: WorkflowArtifact, schema: WorkflowSchema, visiting: set[str]
    ) -> None:
        existing = self.nodes.get(artifact.id)
        if existing is not None:
            if existing.path != artifact.path:
                raise ValueError(
                    f"duplicate workflow artifact id `{artifact.id}` appears at "
                    f"{existing.path} and {artifact.path}"
                )
            return
        if artifact.id in visiting:
            raise ValueError(f"workflow dependency cycle includes `{artifact.id}`")
        visiting.add(artifact.id)
        self.nodes[artifact.id] = artifact
        for dependency in artifact.depends_on:
            child_path = dependency_path(artifact.path, dependency)
            if not child_path.exists():
                self.blockers.append(
                    Blocker("dependency_missing", artifact.id, dependency)
                )
                continue
            child = read_artifact(child_path, schema)
            if child.id in visiting:
                self.blockers.append(Blocker("dependency_cycle", artifact.id, child.id))
                continue
            self._visit(child, schema, visiting)
        visiting.remove(artifact.id)

    def _add_completion_blockers(self, schema: WorkflowSchema) -> None:
        for node in self.nodes.values():
            for dependency in node.depends_on:
                target = self._resolved(dependency)
                if target is None:
                    continue
                if (
                    target.status
                    not in schema.artifact_type(target.artifact_type).completion_states
                ):
                    self.blockers.append(
                        Blocker(
                            "dependency_incomplete", node.id, dependency, target.status
                        )
                    )

    def _resolved(self, reference: str) -> WorkflowArtifact | None:
        return self.nodes.get(reference) or next(
            (
                node
                for node in self.nodes.values()
                if derived_id(node.path) == reference
            ),
            None,
        )

    def _resolved_id(self, reference: str) -> str | None:
        result = self._resolved(reference)
        return result.id if result else None


def read_artifact(path: Path | str, schema: WorkflowSchema) -> WorkflowArtifact:
    source = Path(path)
    try:
        frontmatter, _ = parse(source.read_bytes())
    except (OSError, ValueError) as exc:
        raise ValueError(f"failed to read workflow artifact {source}") from exc
    artifact_type = (
        frontmatter.get("artifact_type") or frontmatter.get("type") or "plan"
    )
    if not isinstance(artifact_type, str):
        raise ValueError(f"artifact `{source}` has invalid artifact type")
    state_schema = schema.artifact_type(artifact_type)
    status = frontmatter.get("status", state_schema.initial_state)
    if not isinstance(status, str) or status not in state_schema.states:
        raise ValueError(f"artifact `{source}` has unknown status `{status}`")
    artifact_id = frontmatter.get("id", derived_id(source))
    if not isinstance(artifact_id, str):
        raise ValueError(f"artifact `{source}` has invalid id")
    dependencies = frontmatter.get("depends_on", [])
    if not isinstance(dependencies, list) or any(
        not isinstance(item, str) for item in dependencies
    ):
        raise ValueError("depends_on must be a sequence of strings")
    return WorkflowArtifact(
        artifact_id, artifact_type, status, sorted(set(dependencies)), source
    )


def dependency_path(source: Path, dependency: str) -> Path:
    if source.name == "plan.md":
        return source.parent.parent.joinpath(dependency, "plan.md")
    return source.parent / f"{dependency}.md"


def derived_id(path: Path) -> str:
    return path.parent.name if path.name == "plan.md" else path.stem


def _json_sort_key(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
