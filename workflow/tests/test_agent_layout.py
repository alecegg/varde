"""Agent bodies state outcomes and validation; how moves to on-request topics."""

from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path

import pytest
from varde_learn.docs import how_cmd
from varde_learn.docs.cli import run

AGENTS = Path(__file__).resolve().parents[1] / "src/varde_workflow/agents"
PROFILES = json.loads((AGENTS / "capabilities.json").read_text())["profiles"]
MAIN = [p for p in PROFILES if (AGENTS / p["name"] / "how").is_dir()]
NUMBERED_STEP = re.compile(r"^\d+\. ", re.MULTILINE)


def test_every_main_agent_has_how_topics():
    assert {p["name"] for p in MAIN} == {
        "varde-planner",
        "varde-builder",
        "varde-reviewer",
        "varde-explorer",
    }


@pytest.mark.parametrize("profile", MAIN, ids=lambda p: p["name"])
def test_body_has_outcomes_validation_and_notice(profile):
    body = profile["instructions"]
    assert "## Validation" in body
    assert "## Outcomes" in body or "## Contract" in body
    assert f"varde learn how {profile['name']} [step]" in body
    assert "unsure, after repeated failure, or on friction" in body
    assert not NUMBERED_STEP.search(body), "step-by-step how belongs in a how topic"


@pytest.mark.parametrize("profile", MAIN, ids=lambda p: p["name"])
def test_every_how_topic_resolves_through_learn_how(profile, capsys):
    name = profile["name"]
    steps = sorted(f.stem for f in (AGENTS / name / "how").glob("*.md"))
    assert steps
    for step in steps:
        assert f"{step}" in profile["instructions"]
        assert run(["how", name, step]) == 0
        assert capsys.readouterr().out.strip()
    assert run(["how", name]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == len(steps)


def test_agent_topics_load_from_the_installed_package():
    topics = how_cmd.load_agent_topics([files("varde_workflow") / "agents"])
    assert set(topics) == {p["name"] for p in MAIN}
