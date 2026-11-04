---
type: task
status: done
depends_on: [base]
owns: [python/varde-workflow/src/varde_workflow/artifact.py, python/varde-workflow/src/varde_workflow/schema.py, python/varde-workflow/src/varde_workflow/graph.py, python/varde-workflow/src/varde_workflow/commands/validate.py, python/varde-workflow/src/varde_workflow/commands/graph.py, python/varde-workflow/tests/test_artifact.py]
---

Port `artifact.rs`, `workflow_schema.rs`, `workflow_graph.rs`, `commands/{validate,graph}.rs` (lint belongs to md-core).

#### Acceptance criteria

- assert: `cd /Users/alec/source/varde-py && uv run pytest python/varde-workflow/tests/test_artifact.py -q` → exit 0

#### Progress

- `varde_workflow.artifact.ArtifactEnvelope(schema_version: int, artifact_type: str, id: str, status: str | None, relationships: Any, provenance: Any, revision: str, source_path: Path)`; `inspect(path: Path | str) -> ArtifactEnvelope`; invalid input raises `ArtifactInvalid` with sorted `Diagnostic(field, message)` entries.
- `varde_workflow.schema.WorkflowSchema.resolve(artifact: Path | str) -> WorkflowSchema`; `artifact_type(name: str) -> ArtifactTypeSchema`; `to_json() -> dict[str, Any]`; `merge_override(schema, value) -> None`.
- `varde_workflow.graph.ArtifactGraph.resolve(path: Path | str, schema: WorkflowSchema) -> ArtifactGraph`; `read_artifact(path: Path | str, schema: WorkflowSchema) -> WorkflowArtifact`; graph methods `root()`, `root_blockers()`, `actions(schema)`, `to_json(schema)`, and `readiness_json(schema)`.
- `varde_workflow.commands.validate.resolve_target(path: Path | str) -> Path`; `validate(path: Path | str) -> tuple[ArtifactEnvelope | None, list[Diagnostic], list[Finding]]`; `status_and_key_findings(path, envelope)`, `text_findings(envelope, path)`, and `blank_progress(text)`.
- `varde_workflow.commands.graph.graph_data(path: str, *, offset: int = 0, limit: int = 100, all_items: bool = False) -> tuple[dict[str, Any], dict[str, Any]]`; `paginate_graph(data, *, offset, limit, all_items=False) -> dict[str, Any]`.
- Check: `uv run pytest python/varde-workflow/tests/test_artifact.py -q` -> 4 passed; `git diff --check` clean.

