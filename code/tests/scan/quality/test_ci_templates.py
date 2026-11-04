"""CI templates are validated as text and YAML, never executed."""

from __future__ import annotations

import json
from importlib.resources import files

import pytest
import yaml

TEMPLATES = ("github-actions.yml", "gitlab-ci.yml")


def _text(name: str) -> str:
    return files("varde_code.scan").joinpath("ci_templates", name).read_text("utf-8")


@pytest.mark.parametrize("name", TEMPLATES)
def test_yaml_parses(name: str) -> None:
    assert isinstance(yaml.safe_load(_text(name)), dict)


@pytest.mark.parametrize("name", TEMPLATES)
def test_names_protected_workflow_and_rules_ref(name: str) -> None:
    text = _text(name)
    assert "PROTECTED WORKFLOW REQUIREMENT" in text
    assert "rulesRef" in text
    assert "severityThreshold" in text
    assert "config-changed" in text
    assert "changedSince" in text


@pytest.mark.parametrize("name", TEMPLATES)
def test_embeds_failure_wording(name: str) -> None:
    wording = _text("failure_wording.txt").strip()
    assert wording.startswith("These findings fail the gate because")
    assert wording in _text(name)


def test_github_scan_json_is_valid() -> None:
    line = next(
        ln
        for ln in _text("github-actions.yml").splitlines()
        if "varde scan --json '" in ln
        and "severityThreshold" in ln
        and not ln.lstrip().startswith("#")
    )
    payload = line.split("--json '", 1)[1].split("'", 1)[0]
    data = json.loads(payload.replace("${{ github.base_ref }}", "main"))
    assert data["severityThreshold"] == "error"
    assert data["rulesRef"] == "origin/main"
