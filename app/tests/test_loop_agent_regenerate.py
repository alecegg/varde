"""Accepting an agent proposal regenerates the harness variants (real generator).

The learn tests cover the proposal and apply logic; these run `app/scripts/generate.py`
on a copy of the real manifest and templates, so they live in the app module.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from varde_learn.docs.pages import comments
from varde_learn.loop import cli_skills_accept, cli_skills_extract, cli_skills_reset
from varde_learn.loop.improve import approval
from varde_learn.loop.improve import record as rec
from varde_learn.memory import store

REPO = Path(__file__).resolve().parents[2]
GENERATOR = REPO / "app/scripts/generate.py"


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


@pytest.fixture
def agent_world(tmp_path, monkeypatch):
    pkg = tmp_path / "pkg"
    agents = pkg / "agents"
    agents.mkdir(parents=True)
    shutil.copy(
        REPO / "workflow/src/varde_workflow/agents/capabilities.json",
        agents / "capabilities.json",
    )
    templates = tmp_path / "tpl"
    shutil.copytree(REPO / "app/templates", templates)

    def regenerate(extra: list[str]) -> bool:
        command = [
            sys.executable,
            str(GENERATOR),
            "--manifest",
            str(agents / "capabilities.json"),
            "--templates",
            str(templates),
            "--output-root",
            str(agents),
            *extra,
        ]
        return subprocess.run(command, check=False, capture_output=True).returncode == 0  # noqa: S603

    assert regenerate([])
    assert regenerate(["--check"])
    memory = tmp_path / "memory"
    monkeypatch.setattr(store, "memory_root", lambda _cwd: memory)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    return pkg, memory, regenerate


def accept(pkg: Path, memory: Path, record_id: str, regenerate, out=None) -> int:
    """Record the user's approval on a report page, then accept."""
    page = approval.report_dir(memory) / "2026-11-01.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f"```ui id={record_id}\n```\n")
    extra = {"kind": "decision", "item": record_id, "verdict": "approved"}
    comments.append_comment(page, "b1", "", "approved", "user", extra)
    return cli_skills_accept.run([record_id], out or Io(), regenerate, roots=[pkg])


def builder_instructions(pkg: Path) -> str:
    caps = json.loads((pkg / "agents/capabilities.json").read_text())
    return next(p for p in caps["profiles"] if p["name"] == "varde-builder")[
        "instructions"
    ]


def test_extract_accept_regenerates_variants(agent_world) -> None:
    pkg, memory, regenerate = agent_world
    assert cli_skills_extract.run(["varde-builder", "handoff"], Io(), roots=[pkg]) == 0
    [record] = rec.list_records(memory)
    assert accept(pkg, memory, record.id, regenerate) == 0
    assert regenerate(["--check"])
    assert 'step-tool" varde-builder/handoff' in builder_instructions(pkg)
    variant = (pkg / "agents/varde-builder/claude.md").read_text()
    assert 'step-tool" varde-builder/handoff' in variant
    assert (pkg / "agents/varde-builder/how/handoff.md").is_file()
    assert rec.read_record(memory, record.id).state == "applied"


def test_reset_accept_regenerates_variants(agent_world) -> None:
    pkg, memory, regenerate = agent_world
    args = ["varde-builder", "--model", "m-2", "--harness-version", "9.1"]
    before = {str(p) for p in pkg.rglob("*") if p.is_file()}
    assert cli_skills_reset.run(args, Io(), roots=[pkg], demand=lambda _s: {}) == 0
    assert {str(p) for p in pkg.rglob("*") if p.is_file()} == before
    [record] = rec.list_records(memory)
    diff = rec.read_diff(memory, record)
    assert "capabilities.json" in diff and "/how/pipeline-mode.md" in diff
    assert "claude.md" not in diff
    assert accept(pkg, memory, record.id, regenerate) == 0
    assert regenerate(["--check"])
    assert "how: pipeline-mode - Pipeline mode" in builder_instructions(pkg)
    assert (pkg / "agents/varde-builder/how/pipeline-mode.md").is_file()


def test_failed_regeneration_restores_files(agent_world) -> None:
    pkg, memory, _ = agent_world
    cli_skills_extract.run(["varde-builder", "handoff"], Io(), roots=[pkg])
    [record] = rec.list_records(memory)
    caps = (pkg / "agents/capabilities.json").read_text()
    out = Io()
    assert accept(pkg, memory, record.id, lambda _extra: False, out) == 2
    assert "restored" in out.stderr.getvalue()
    assert (pkg / "agents/capabilities.json").read_text() == caps
    assert not (pkg / "agents/varde-builder/how/handoff.md").exists()
    assert rec.read_record(memory, record.id).state == "proposed"
