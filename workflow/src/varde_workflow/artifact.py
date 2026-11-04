"""Inspection and validation of workflow artifact frontmatter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_learn.knowledge.frontmatter import parse
from varde_learn.knowledge.occ import version


@dataclass(frozen=True)
class Diagnostic:
    field: str
    message: str

    def to_json(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message}


@dataclass(frozen=True)
class ArtifactEnvelope:
    schema_version: int
    artifact_type: str
    id: str
    status: str | None
    relationships: Any
    provenance: Any
    revision: str
    source_path: Path

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_type": self.artifact_type,
            "id": self.id,
            "status": self.status,
            "relationships": self.relationships,
            "provenance": self.provenance,
            "revision": self.revision,
            "source_path": str(self.source_path),
        }


def inspect(path: Path | str) -> ArtifactEnvelope:
    source = Path(path)
    try:
        data = source.read_bytes()
    except OSError as exc:
        message = f"{exc.strerror or exc.__class__.__name__} (os error {exc.errno})"
        raise ArtifactInvalid([Diagnostic("document", message)]) from exc
    revision = version(data)
    try:
        frontmatter, body = parse(data)
    except ValueError as exc:
        raise ArtifactInvalid([Diagnostic("frontmatter", str(exc))]) from exc
    if "schema_version" in frontmatter:
        envelope = _versioned(source, frontmatter, revision)
    else:
        envelope = _plain(source, frontmatter, revision)
    diagnostics = []
    if envelope.artifact_type == "plan":
        if not _has_acceptance(body):
            diagnostics.append(
                Diagnostic("body", "plan is missing a `## Acceptance criteria` section")
            )
        generated = frontmatter.get("generated")
        if "generated" in frontmatter and (
            not isinstance(generated, list)
            or any(not isinstance(item, str) for item in generated)
        ):
            message = (
                "field must contain only strings"
                if isinstance(generated, list)
                else "field must be a list of strings"
            )
            diagnostics.append(Diagnostic("generated", message))
    if diagnostics:
        raise ArtifactInvalid(sorted(diagnostics, key=lambda item: item.field))
    return envelope


class ArtifactInvalid(ValueError):
    def __init__(self, diagnostics: list[Diagnostic]):
        self.diagnostics = diagnostics
        super().__init__("; ".join(item.message for item in diagnostics))


def _versioned(path: Path, mapping: dict[str, Any], revision: str) -> ArtifactEnvelope:
    diagnostics: list[Diagnostic] = []
    schema_version = mapping.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version < 0
    ):
        diagnostics.append(
            Diagnostic("schema_version", "required unsigned integer is missing")
        )
        schema_version = None
    elif schema_version != 1:
        diagnostics.append(
            Diagnostic("schema_version", f"unsupported schema version {schema_version}")
        )
    artifact_type = _required_string(mapping, "artifact_type", diagnostics)
    artifact_id = _required_string(mapping, "id", diagnostics)
    relationships = _required_value(mapping, "relationships", diagnostics)
    if relationships is not None and not isinstance(relationships, list):
        diagnostics.append(Diagnostic("relationships", "field must be a sequence"))
    provenance = _required_value(mapping, "provenance", diagnostics)
    if provenance is not None and not isinstance(provenance, dict):
        diagnostics.append(Diagnostic("provenance", "field must be a mapping"))
    status = mapping.get("status")
    if "status" in mapping and not isinstance(status, str):
        diagnostics.append(Diagnostic("status", "field must be a string"))
        status = None
    if diagnostics:
        raise ArtifactInvalid(sorted(diagnostics, key=lambda item: item.field))
    if schema_version is None:
        raise AssertionError("valid artifact must include schema_version")
    return ArtifactEnvelope(
        schema_version,
        artifact_type,
        artifact_id,
        status,
        relationships,
        provenance,
        revision,
        path,
    )


def _required_string(
    mapping: dict[str, Any], name: str, diagnostics: list[Diagnostic]
) -> str:
    value = mapping.get(name)
    if isinstance(value, str) and value:
        return value
    diagnostics.append(Diagnostic(name, "required non-empty string is missing"))
    return ""


def _required_value(
    mapping: dict[str, Any], name: str, diagnostics: list[Diagnostic]
) -> Any:
    if name in mapping:
        return mapping[name]
    diagnostics.append(Diagnostic(name, "required field is missing"))
    return None


def _plain(path: Path, mapping: dict[str, Any], revision: str) -> ArtifactEnvelope:
    stem = path.stem or ""
    artifact_id = path.parent.name if stem == "plan" else stem
    artifact_type = mapping.get("type")
    status = mapping.get("status")
    return ArtifactEnvelope(
        1,
        artifact_type if isinstance(artifact_type, str) else "document",
        artifact_id,
        status if isinstance(status, str) else None,
        [],
        {"source": "derived", "path": str(path)},
        revision,
        path,
    )


def _has_acceptance(body: str) -> bool:
    for line in body.splitlines():
        stripped = line.lstrip(" ")
        if stripped.startswith("## ") and stripped[3:].strip() == "Acceptance criteria":
            return True
    return False
