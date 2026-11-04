"""Tests for varde_core.layer_check."""

from __future__ import annotations

from pathlib import Path

from varde_core.layer_check import layer_violations

LAYERS = """\
[module.core]
dist = "varde-core"
level = 0

[module.workflow]
dist = "varde-workflow"
level = 3

[module.app]
dist = "varde"
level = 4
"""


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "layers.toml").write_text(LAYERS, encoding="utf-8")
    for module, package in (
        ("core", "varde_core"),
        ("workflow", "varde_workflow"),
        ("app", "varde"),
    ):
        source = tmp_path / module / "src" / package
        source.mkdir(parents=True)
        (source / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


def test_higher_level_import_is_reported_with_path(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    bad = workspace / "workflow" / "src" / "varde_workflow" / "bad.py"
    bad.write_text("from varde import cli\n", encoding="utf-8")

    errors = layer_violations(workspace, [bad])

    assert len(errors) == 1
    assert errors[0].startswith("workflow/src/varde_workflow/bad.py:")
    assert "varde" in errors[0]


def test_lower_level_and_external_imports_are_clean(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    good = workspace / "workflow" / "src" / "varde_workflow" / "good.py"
    good.write_text("import os\nimport varde_core.layout\n", encoding="utf-8")

    assert layer_violations(workspace, [good]) == []


def test_unparseable_file_is_reported_not_raised(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    broken = workspace / "workflow" / "src" / "varde_workflow" / "broken.py"
    broken.write_text("def (:\n", encoding="utf-8")

    errors = layer_violations(workspace, [broken])

    assert len(errors) == 1
    assert errors[0].startswith("workflow/src/varde_workflow/broken.py: cannot parse")
