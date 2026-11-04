"""candidates -> reset proposal -> report page -> accept|reject -> record."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest
from varde_learn.docs.pages.blocks.fences import find_fences
from varde_learn.docs.pages.blocks.lines_check import check_lines
from varde_learn.loop import (
    cli_skills_accept,
    cli_skills_candidates,
    cli_skills_reject,
    cli_skills_report,
    cli_skills_reset,
)
from varde_learn.loop.improve import record as rec
from varde_learn.memory import store

FIXTURE = Path(__file__).parents[1] / "fixtures" / "improve-reset" / "skills"
ARGS = ["--model", "m-2", "--harness-version", "9.1"]


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


def demand(_skill: str | None = None) -> dict:
    return {
        "steps": [{"step": "varde-x/a", "requests": 4, "failures": 1, "friction": 2}],
        "skills": [
            {"skill": "varde-x", "friction_items": 2, "how_skip_friction": 0},
            {"skill": "varde-y", "friction_items": 1, "how_skip_friction": 0},
        ],
    }


@pytest.fixture
def world(tmp_path, monkeypatch):
    pkg = tmp_path / "pkg"
    shutil.copytree(FIXTURE, pkg / "skills")
    shutil.copytree(pkg / "skills" / "varde-x", pkg / "skills" / "varde-y")
    memory = tmp_path / "memory"
    monkeypatch.setattr(store, "memory_root", lambda _cwd: memory)
    return pkg, memory


def snapshot(root: Path) -> dict[str, str]:
    return {str(p): p.read_text() for p in sorted(root.rglob("*")) if p.is_file()}


def test_loop_from_candidates_to_accept_and_reject(world, approve) -> None:
    pkg, memory = world
    out = Io()
    assert cli_skills_candidates.run(["--json", str(pkg)], out, demand=demand) == 0
    ranked = json.loads(out.stdout.getvalue())["data"]["directions"]["add"]
    assert [c["name"] for c in ranked] == ["varde-x", "varde-y"]

    for name in ("varde-x", "varde-y"):
        code = cli_skills_reset.run([name, *ARGS], Io(), roots=[pkg], demand=demand)
        assert code == 0
    before = snapshot(pkg)

    report = Io()
    assert cli_skills_report.run(["--json"], report) == 0
    page = Path(json.loads(report.stdout.getvalue())["data"]["page"])
    fences = find_fences(page.read_text(), frozenset({"ui"}))
    assert len(fences) == 2
    for fence in fences:
        assert check_lines(fence.body) == []
    assert snapshot(pkg) == before

    x, y = sorted(rec.list_records(memory), key=lambda r: r.skill)
    assert cli_skills_reject.run([y.id], Io()) == 0
    assert snapshot(pkg) == before
    assert rec.read_record(memory, y.id).decision == "rejected"

    assert cli_skills_accept.run([x.id], Io(), roots=[pkg]) == 2
    approve(memory, x.id)
    assert cli_skills_accept.run([x.id], Io(), roots=[pkg]) == 0
    done = rec.read_record(memory, x.id)
    assert (done.state, done.decision) == ("applied", "accepted")
    assert done.later_demand["before requests"] == 4
    assert done.token_delta < 0
    assert (
        "First read every input file"
        not in (pkg / "skills/varde-x/SKILL.md").read_text()
    )
