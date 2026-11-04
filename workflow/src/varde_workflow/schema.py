"""Built-in workflow state machines and project schema extensions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_learn.knowledge.formats import load_yaml
from varde_learn.knowledge.memory import MemoryPaths, find_root
from varde_learn.knowledge.occ import version

SCHEMA_VERSION = 1
OVERRIDE_PATH = "workflow/schema.yml"
TASK_ACTIVE = ("in_progress", "building", "in_review", "fixing", "integrating")


@dataclass
class ArtifactTypeSchema:
    initial_state: str
    states: set[str]
    completion_states: set[str]
    transitions: dict[str, set[str]]


@dataclass
class WorkflowSchema:
    artifact_types: dict[str, ArtifactTypeSchema]
    project_schema: Path | None = None
    project_schema_revision: str | None = None

    @classmethod
    def resolve(cls, artifact: Path | str) -> WorkflowSchema:
        schema = built_in()
        root = find_root(artifact)
        if root is None:
            return schema
        path = MemoryPaths.resolve(root).knowledge.path / OVERRIDE_PATH
        if not path.exists():
            return schema
        data = path.read_bytes()
        try:
            override = load_yaml(data.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise ValueError(f"failed to parse workflow schema {path}: {exc}") from exc
        merge_override(schema, override)
        schema.project_schema = path
        schema.project_schema_revision = version(data)
        return schema

    def artifact_type(self, name: str) -> ArtifactTypeSchema:
        try:
            return self.artifact_types[name]
        except KeyError as exc:
            raise ValueError(f"unknown workflow artifact type `{name}`") from exc

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "artifact_types": {
                name: {
                    "initial_state": item.initial_state,
                    "states": sorted(item.states),
                    "completion_states": sorted(item.completion_states),
                    "transitions": {
                        source: sorted(targets)
                        for source, targets in sorted(item.transitions.items())
                    },
                }
                for name, item in sorted(self.artifact_types.items())
            },
            "project_schema": str(self.project_schema) if self.project_schema else None,
        }


def built_in() -> WorkflowSchema:
    return WorkflowSchema(
        {
            "plan": _machine(
                "backlog",
                ["active", "backlog", "blocked", "cancelled", "completed"],
                ["cancelled", "completed"],
                {
                    "backlog": ["active", "blocked"],
                    "active": ["blocked", "completed"],
                    "blocked": ["active"],
                    "cancelled": [],
                    "completed": [],
                },
            ),
            "task": _machine(
                "todo",
                ["blocked", "done", *TASK_ACTIVE, "todo"],
                ["done"],
                _task_transitions(),
            ),
        }
    )


def can_transition(machine: ArtifactTypeSchema, source: str, target: str) -> bool:
    """Return whether a state change is allowed by an artifact state machine."""
    return source in machine.states and target in machine.transitions.get(source, set())


def _task_transitions() -> dict[str, list[str]]:
    transitions = {
        state: [
            "blocked",
            *[target for target in TASK_ACTIVE if target != state],
            "done",
        ]
        for state in TASK_ACTIVE
    }
    transitions["todo"] = ["blocked", *TASK_ACTIVE]
    transitions["blocked"] = list(TASK_ACTIVE)
    transitions["done"] = []
    return transitions


def _machine(
    initial: str,
    states: list[str],
    completion: list[str],
    transitions: dict[str, list[str]],
) -> ArtifactTypeSchema:
    return ArtifactTypeSchema(
        initial,
        set(states),
        set(completion),
        {key: set(values) for key, values in transitions.items()},
    )


def merge_override(schema: WorkflowSchema, value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("workflow schema must be a mapping")
    version_value = value.get("schema_version")
    if not isinstance(version_value, int) or isinstance(version_value, bool):
        raise ValueError("workflow schema requires `schema_version`")
    if version_value != SCHEMA_VERSION:
        raise ValueError(f"unsupported workflow schema version {version_value}")
    additions = value.get("artifact_types")
    if not isinstance(additions, dict):
        raise ValueError("workflow schema requires `artifact_types` mapping")
    for name, definition in additions.items():
        if not isinstance(name, str):
            raise ValueError("workflow artifact type names must be strings")
        if name in schema.artifact_types:
            raise ValueError(
                f"project schema cannot replace core artifact type `{name}`"
            )
        schema.artifact_types[name] = _parse_artifact_type(name, definition)


def _parse_artifact_type(name: str, value: Any) -> ArtifactTypeSchema:
    if not isinstance(value, dict):
        raise ValueError(f"artifact type `{name}` must be a mapping")
    initial = _required_string(value, "initial_state")
    states = _required_strings(value, "states")
    completion = _required_strings(value, "completion_states")
    if initial not in states:
        raise ValueError(
            f"artifact type `{name}` has an unknown initial state `{initial}`"
        )
    for state in completion:
        if state not in states:
            raise ValueError(
                f"artifact type `{name}` has an unknown completion state `{state}`"
            )
    raw_transitions = value.get("transitions")
    if not isinstance(raw_transitions, dict):
        raise ValueError(f"artifact type `{name}` requires `transitions` mapping")
    transitions: dict[str, set[str]] = {}
    for source, targets in raw_transitions.items():
        if not isinstance(source, str):
            raise ValueError(f"artifact type `{name}` transition keys must be strings")
        if source not in states:
            raise ValueError(
                f"artifact type `{name}` has an unknown transition state `{source}`"
            )
        target_set = _string_sequence(targets, "transition targets")
        for target in target_set:
            if target not in states:
                raise ValueError(
                    f"artifact type `{name}` has an unknown transition target "
                    f"`{target}`"
                )
        transitions[source] = target_set
    for state in states:
        transitions.setdefault(state, set())
    return ArtifactTypeSchema(initial, states, completion, transitions)


def _required_string(mapping: dict[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str):
        raise ValueError(f"workflow schema requires string `{field}`")
    return value


def _required_strings(mapping: dict[str, Any], field: str) -> set[str]:
    if field not in mapping:
        raise ValueError(f"workflow schema requires `{field}`")
    return _string_sequence(mapping[field], field)


def _string_sequence(value: Any, field: str) -> set[str]:
    if not isinstance(value, list):
        raise ValueError(f"workflow schema `{field}` must be a sequence")
    if any(not isinstance(item, str) for item in value):
        raise ValueError(f"workflow schema `{field}` entries must be strings")
    return set(value)
