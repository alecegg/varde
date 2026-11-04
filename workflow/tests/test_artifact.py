from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_workflow.artifact import ArtifactInvalid, inspect
from varde_workflow.commands.readiness import run as run_readiness
from varde_workflow.commands.validate import run as run_validate
from varde_workflow.commands.validate import validate
from varde_workflow.graph import ArtifactGraph
from varde_workflow.schema import WorkflowSchema


def test_inspects_plain_plan_and_derives_directory_id(tmp_path: Path) -> None:
    plan_dir = tmp_path / "plans" / "example-plan"
    plan_dir.mkdir(parents=True)
    path = plan_dir / "plan.md"
    path.write_text(
        "---\ntype: plan\nstatus: active\n---\n## Acceptance criteria\n- works\n",
        encoding="utf-8",
    )

    artifact = inspect(path)

    assert artifact.id == "example-plan"
    assert artifact.artifact_type == "plan"
    assert artifact.to_json()["provenance"] == {"source": "derived", "path": str(path)}


def test_versioned_artifact_collects_sorted_validation_diagnostics(
    tmp_path: Path,
) -> None:
    path = tmp_path / "task.md"
    path.write_text(
        "---\nschema_version: 2\nartifact_type: ''\nid: ''\n"
        "relationships: nope\nprovenance: []\nstatus: 1\n---\n",
        encoding="utf-8",
    )

    with pytest.raises(ArtifactInvalid) as error:
        inspect(path)

    assert [item.field for item in error.value.diagnostics] == [
        "artifact_type",
        "id",
        "provenance",
        "relationships",
        "schema_version",
        "status",
    ]


def test_validation_preserves_all_plan_inline_list_warnings() -> None:
    path = (
        Path(__file__).parent
        / "fixtures/plan-stores/active/plans/sample-workflow/plan.md"
    )

    artifact, errors, warnings = validate(path)

    assert artifact is not None
    assert errors == []
    text_warnings = [
        warning
        for warning in warnings
        if warning.message
        not in {
            "missing label",
            "missing group",
            "label must be 3 to 5 words",
        }
        and "sentence" not in warning.message
    ]
    assert [warning.line for warning in text_warnings] == [15, 25, 32]


def test_validate_reports_task_ownership_escape_and_missing_paths(
    tmp_path: Path,
) -> None:
    plan_dir = tmp_path / "plans" / "example"
    tasks = plan_dir / "tasks"
    tasks.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        "---\ntype: plan\nstatus: active\nlabel: Clean Plan Validation\n"
        "group: Tests\n---\n"
        "## Acceptance criteria\n- valid\n",
        encoding="utf-8",
    )
    (tasks / "bad.md").write_text(
        "---\ntype: task\nstatus: todo\nowns: [/outside.py]\n"
        "modifies: [missing.py]\n---\n## Acceptance criteria\n- valid\n",
        encoding="utf-8",
    )
    (tmp_path / "repo").mkdir()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    artifact, errors, _ = validate(plan_dir / "plan.md")
    assert artifact is None
    assert [item.field for item in errors] == [
        "tasks.bad.ownership",
        "tasks.bad.ownership",
    ]
    assert any("escapes repository" in item.message for item in errors)
    assert any("path does not exist" in item.message for item in errors)


def test_validate_skips_ownership_for_cancelled_plan(tmp_path: Path) -> None:
    plan_dir = tmp_path / "plans" / "cancelled"
    tasks = plan_dir / "tasks"
    tasks.mkdir(parents=True)
    plan = plan_dir / "plan.md"
    plan.write_text(
        "---\ntype: plan\nstatus: cancelled\n---\n## Acceptance criteria\n- done\n",
        encoding="utf-8",
    )
    (tasks / "missing.md").write_text(
        "---\ntype: task\nstatus: todo\nowns: [never-created/**]\n---\n",
        encoding="utf-8",
    )
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    artifact, errors, _ = validate(plan)

    assert artifact is not None
    assert errors == []


def test_validate_clean_plan_omits_text_warnings_and_matches_text_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "plan.md"
    path.write_text(
        "---\ntype: plan\nstatus: active\nlabel: Clean Plan Validation\n"
        "group: Tests\n---\n"
        "## Acceptance criteria\n- valid\n",
        encoding="utf-8",
    )
    assert run_validate(SimpleNamespace(artifact=str(path), json=True)) == 0
    assert "text_warnings" not in json.loads(capsys.readouterr().out)["data"]
    assert run_validate(SimpleNamespace(artifact=str(path), json=False)) == 0
    assert capsys.readouterr().out == f"valid: {path}\n"


def test_validate_metadata_warnings_do_not_change_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "plan.md"
    path.write_text(
        "---\ntype: plan\nstatus: active\n---\n## Acceptance criteria\n- valid\n",
        encoding="utf-8",
    )

    code = run_validate(SimpleNamespace(artifact=str(path), json=False))

    output = capsys.readouterr().out
    assert code == 0
    assert output.startswith(f"valid: {path}\n")
    assert "warn:" in output
    assert "missing label" in output
    assert "missing group" in output


def test_validate_warns_for_wrong_label_word_count(tmp_path: Path) -> None:
    path = tmp_path / "plans" / "example" / "plan.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\ntype: plan\nstatus: active\ntitle: Fix Mobile Plans scrolling\n"
        "label: One\ngroup: Tests\n---\n"
        "## Acceptance criteria\n- valid\n",
        encoding="utf-8",
    )

    artifact, errors, warnings = validate(path)

    assert artifact is not None
    assert errors == []
    assert [warning.message for warning in warnings] == [
        'label must be 3 to 5 words; suggest: "Fix Mobile Plans scrolling"'
    ]


def test_validate_warns_for_duplicate_open_sibling_label(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    first = plans / "first" / "plan.md"
    second = plans / "second" / "plan.md"
    first.parent.mkdir(parents=True)
    second.parent.mkdir()
    first.write_text(
        "---\ntype: plan\nstatus: active\nlabel: Fix Mobile Plans\ngroup: Tests\n---\n",
        encoding="utf-8",
    )
    second.write_text(
        "---\ntype: plan\nstatus: active\nlabel: fix mobile plans\n"
        "title: Retune Mobile Plans scrolling\ngroup: Tests\n---\n"
        "## Acceptance criteria\n- valid\n",
        encoding="utf-8",
    )

    artifact, errors, warnings = validate(second)

    assert artifact is not None
    assert errors == []
    assert [warning.message for warning in warnings] == [
        (
            "label must be unique among open plans; suggest: "
            '"Retune Mobile Plans scrolling"'
        )
    ]


def test_validate_warns_for_duplicate_label_in_nested_plan(tmp_path: Path) -> None:
    parent = tmp_path / "plans" / "parent" / "plan.md"
    child = tmp_path / "plans" / "parent" / "plans" / "child" / "plan.md"
    parent.parent.mkdir(parents=True)
    child.parent.mkdir(parents=True)
    content = (
        "---\ntype: plan\nstatus: active\nlabel: Shared Plan Label\ngroup: Tests\n---\n"
        "## Acceptance criteria\n- Valid plan\n"
    )
    parent.write_text(content, encoding="utf-8")
    child.write_text(content, encoding="utf-8")

    _, _, warnings = validate(child)

    assert any(
        warning.message.startswith("label must be unique") for warning in warnings
    ), warnings


def test_validate_blank_label_warns_as_missing(tmp_path: Path) -> None:
    path = tmp_path / "plans" / "example" / "plan.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\ntype: plan\nstatus: active\nlabel: ''\ngroup: Tests\n---\n"
        "## Acceptance criteria\n- valid\n",
        encoding="utf-8",
    )

    artifact, errors, warnings = validate(path)

    assert artifact is not None
    assert errors == []
    assert [warning.message for warning in warnings] == ["missing label"]


def test_validate_uses_inherited_group_for_metadata_warnings(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "plans" / "parent"
    parent.mkdir(parents=True)
    (parent / "plan.md").write_text(
        "---\ntype: plan\nstatus: active\ngroup: Quality score\n---\n"
        "## Acceptance criteria\n- valid\n",
        encoding="utf-8",
    )
    child = parent / "child" / "plan.md"
    child.parent.mkdir()
    child.write_text(
        "---\ntype: plan\nstatus: active\nlabel: Safe Progress Plan\n---\n"
        "## Acceptance criteria\n- valid\n",
        encoding="utf-8",
    )

    artifact, errors, warnings = validate(child)

    assert artifact is not None
    assert errors == []
    assert [warning.message for warning in warnings] == []


def test_validate_ignores_plan_outside_plans_ancestor_chain(tmp_path: Path) -> None:
    outside = tmp_path / "plan.md"
    outside.write_text(
        "---\ntype: plan\nstatus: active\ngroup: Outside\n---\n",
        encoding="utf-8",
    )
    child = tmp_path / "plans" / "child" / "plan.md"
    child.parent.mkdir(parents=True)
    child.write_text(
        "---\ntype: plan\nstatus: active\nlabel: Safe Progress Plan\n---\n"
        "## Acceptance criteria\n- valid\n",
        encoding="utf-8",
    )

    artifact, errors, warnings = validate(child)

    assert artifact is not None
    assert errors == []
    assert [warning.message for warning in warnings] == ["missing group"]


def test_validate_falls_back_past_unreadable_parent(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    grandparent = plans / "grandparent" / "plan.md"
    grandparent.parent.mkdir(parents=True)
    grandparent.write_text(
        "---\ntype: plan\nstatus: active\ngroup: Quality score\n---\n",
        encoding="utf-8",
    )
    parent = grandparent.parent / "parent" / "plan.md"
    parent.parent.mkdir()
    parent.write_text("---\ntype: plan\ngroup: [bad\n---\n", encoding="utf-8")
    child = parent.parent / "child" / "plan.md"
    child.parent.mkdir()
    child.write_text(
        "---\ntype: plan\nstatus: active\nlabel: Safe Progress Plan\n---\n"
        "## Acceptance criteria\n- valid\n",
        encoding="utf-8",
    )

    artifact, errors, warnings = validate(child)

    assert artifact is not None
    assert errors == []
    assert warnings == []


def test_graph_resolves_dependencies_and_readiness(tmp_path: Path) -> None:
    parent = tmp_path / "plans" / "parent"
    dependency = tmp_path / "plans" / "dependency"
    parent.mkdir(parents=True)
    dependency.mkdir(parents=True)
    (parent / "plan.md").write_text(
        "---\ntype: plan\nstatus: active\ndepends_on: [dependency]\n---\n",
        encoding="utf-8",
    )
    (dependency / "plan.md").write_text(
        "---\ntype: plan\nstatus: completed\n---\n", encoding="utf-8"
    )

    schema = WorkflowSchema.resolve(parent / "plan.md")
    graph = ArtifactGraph.resolve(parent / "plan.md", schema)

    assert graph.readiness_json(schema)["ready"] is True
    assert graph.to_json(schema)["edges"] == [
        {"from": "parent", "to": "dependency", "relationship": "depends_on"}
    ]


def test_task_rooted_graph_sorts_nodes_by_id(tmp_path: Path) -> None:
    task = tmp_path / "tasks" / "z-root.md"
    task.parent.mkdir()
    task.write_text(
        "---\ntype: task\nstatus: todo\ndepends_on: [a-child]\n---\n", encoding="utf-8"
    )
    (task.parent / "a-child.md").write_text(
        "---\ntype: task\nstatus: done\n---\n", encoding="utf-8"
    )
    schema = WorkflowSchema.resolve(task)
    graph = ArtifactGraph.resolve(task, schema)
    assert [node["id"] for node in graph.to_json(schema)["nodes"]] == [
        "a-child",
        "z-root",
    ]


def test_schema_override_adds_types_and_rejects_core_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setenv("VARDE_KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
    override = tmp_path / "knowledge" / "workflow" / "schema.yml"
    override.parent.mkdir(parents=True)
    override.write_text(
        "schema_version: 1\n"
        "artifact_types:\n"
        "  decision:\n"
        "    initial_state: proposed\n"
        "    states: [proposed, accepted]\n"
        "    completion_states: [accepted]\n"
        "    transitions:\n"
        "      proposed: [accepted]\n",
        encoding="utf-8",
    )
    artifact = tmp_path / "plan.md"

    schema = WorkflowSchema.resolve(artifact)

    assert schema.artifact_type("decision").initial_state == "proposed"
    assert schema.project_schema == override.resolve()
    assert schema.project_schema_revision
    assert schema.to_json()["artifact_types"]["task"]["initial_state"] == "todo"

    override.write_text(
        "schema_version: 1\nartifact_types:\n  task: {}\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="cannot replace core artifact type `task`"):
        WorkflowSchema.resolve(artifact)


def test_readiness_json_uses_cli_sorted_envelope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "plan.md"
    path.write_text("---\ntype: plan\nstatus: active\n---\n", encoding="utf-8")

    assert run_readiness(SimpleNamespace(plan=str(path), json=True)) == 0

    output = capsys.readouterr().out
    assert output.startswith('{"data":')
    assert json.loads(output)["data"]["ready"] is True
