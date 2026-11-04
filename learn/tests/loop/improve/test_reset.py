from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
from varde_learn.loop import cli_skills_accept, cli_skills_extract, cli_skills_reset
from varde_learn.loop.improve import extract, reset
from varde_learn.loop.improve import record as rec
from varde_learn.memory import store

FIXTURE = Path(__file__).parents[1] / "fixtures" / "improve-reset"
ARGS = ["--model", "m-2", "--harness-version", "9.1"]


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


def demand(_skill: str) -> dict:
    return {"steps": [{"requests": 4, "failures": 1, "friction": 2}]}


@pytest.fixture
def world(tmp_path, monkeypatch):
    pkg = tmp_path / "pkg"
    shutil.copytree(FIXTURE / "skills", pkg / "skills")
    memory = tmp_path / "memory"
    monkeypatch.setattr(store, "memory_root", lambda _cwd: memory)
    return pkg, memory


def snapshot(root: Path) -> dict[str, str]:
    return {str(p): p.read_text() for p in sorted(root.rglob("*")) if p.is_file()}


def run(pkg, args, d=demand):
    out = Io()
    return cli_skills_reset.run(args, out, roots=[pkg], demand=d), out


def test_dry_run_writes_nothing(world) -> None:
    pkg, memory = world
    before = snapshot(pkg)
    code, out = run(pkg, ["varde-x", *ARGS, "--dry-run"])
    assert code == 0
    assert "+how: procedure - Procedure" in out.stdout.getvalue()
    assert not memory.exists()
    assert snapshot(pkg) == before


def test_real_run_writes_proposal_with_versions_and_counts(world) -> None:
    pkg, memory = world
    before = snapshot(pkg)
    assert run(pkg, ["varde-x", *ARGS])[0] == 0
    assert snapshot(pkg) == before
    [record] = rec.list_records(memory)
    assert record.direction == "reset" and record.state == "proposed"
    assert reset.versions_of(record) == ("m-2", "9.1")
    assert record.later_demand["before requests"] == 4
    assert record.later_demand["before failures"] == 1
    assert (
        record.later_demand["route tokens after"]
        < record.later_demand["route tokens before"]
    )
    assert record.token_delta < 0


def test_accept_leaves_outcomes_validation_and_topics(world, approve) -> None:
    pkg, memory = world
    run(pkg, ["varde-x", *ARGS])
    [record] = rec.list_records(memory)
    approve(memory, record.id)
    assert cli_skills_accept.run([record.id], Io(), roots=[pkg]) == 0
    text = (pkg / "skills/varde-x/SKILL.md").read_text()
    assert "## Outcomes" in text and "## Validation" in text
    assert "First read every input file" not in text
    assert "## Topics" in text
    assert "how: procedure - Procedure" in text
    assert "how: edge-cases - Edge cases" in text
    procedure = (pkg / "how/varde-x/procedure.md").read_text()
    assert "First read every input file" in procedure
    assert "topic: varde-x/procedure" in procedure
    assert "binary" in (pkg / "how/varde-x/edge-cases.md").read_text()


def test_existing_topics_section_gets_how_lines() -> None:
    text = (
        "# S\n\n## Topics\n\nRequest it.\n\nhow: old - Old\n\n## Extra\n\nbody text\n"
    )
    new, moved = reset.slim_text(text, "Topics", "varde learn how s <step>")
    assert [m.step for m in moved] == ["extra"]
    assert (
        new == "# S\n\n## Topics\n\nRequest it.\n\nhow: old - Old\nhow: extra - Extra\n"
    )


def test_headingless_text_has_no_spans_and_is_already_slim() -> None:
    assert extract.find_section_spans("no heads\n") == []
    with pytest.raises(reset.AlreadySlim):
        reset.slim_text("no heads\n", "Topics", "c")


def test_every_section_moves_appends_topics_section() -> None:
    text = "# S\n\n## One\n\na\n\n## Two\n\nb\n"
    new, moved = reset.slim_text(text, "Topics", "varde learn how s <step>")
    assert [m.step for m in moved] == ["one", "two"]
    assert "## Topics" in new
    assert new.endswith("how: one - One\nhow: two - Two\n")


def test_reset_on_headingless_skill_is_refused_as_already_slim(world) -> None:
    pkg, _ = world
    skill = pkg / "skills" / "varde-flat"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: varde-flat\n---\n\nno heads\n")
    code, out = run(pkg, ["varde-flat", *ARGS])
    assert code == 2
    assert "already slim" in out.stderr.getvalue()
    assert "zip" not in out.stderr.getvalue()


def test_already_slim_and_clashing_topic_are_refused(world) -> None:
    pkg, _ = world
    with pytest.raises(extract.ExtractError, match="already slim"):
        reset.slim_text("# S\n\n## Outcomes\n\nx\n", "Topics", "c")
    (pkg / "how/varde-x").mkdir(parents=True)
    (pkg / "how/varde-x/procedure.md").write_text("x")
    code, out = run(pkg, ["varde-x", *ARGS])
    assert code == 2 and "already exists" in out.stderr.getvalue()


def test_usage_requires_versions(world) -> None:
    pkg, _ = world
    assert run(pkg, ["varde-x"])[0] == 2
    assert run(pkg, ["varde-x", "--model", "m"])[0] == 2
    assert run(pkg, ["nope", *ARGS])[0] == 2


def test_comparison_after_an_applied_reset(world, approve) -> None:
    pkg, memory = world
    run(pkg, ["varde-x", *ARGS])
    [record] = rec.list_records(memory)
    approve(memory, record.id)
    cli_skills_accept.run([record.id], Io(), roots=[pkg])
    later = {"steps": [{"requests": 6, "failures": 0, "friction": 2}]}
    code, out = run(pkg, ["varde-x", *ARGS], lambda _s: later)
    assert code == 0
    assert "requests: before 4, now 6" in out.stdout.getvalue()
    assert len(rec.list_records(memory)) == 1
    applied = rec.read_record(memory, record.id)
    assert reset.compare(applied, {"requests": 6, "failures": 0, "friction": 2}) == {
        "requests": (4, 6),
        "failures": (1, 0),
        "friction": (2, 2),
    }


@pytest.mark.parametrize(
    ("body", "slim"),
    [("# S\n\n## One\n\n" + "word " * 400 + "\n", False), ("# S\n\nshort\n", True)],
)
def test_skill_without_how_topics_plans_or_is_already_slim(
    tmp_path: Path, body: str, slim: bool
) -> None:
    skill_md = tmp_path / "skills" / "s" / "SKILL.md"
    skill_md.parent.mkdir(parents=True)
    skill_md.write_text(body)
    how_dir = tmp_path / "how" / "s"
    if slim:
        with pytest.raises(reset.AlreadySlim):
            reset.plan_skill_reset("s", skill_md, body, how_dir, set())
        return
    plan = reset.plan_skill_reset("s", skill_md, body, how_dir, set())
    assert plan.changes[0].path == str(skill_md)


def test_extract_without_a_step_points_to_reset(tmp_path: Path) -> None:
    out = Io()
    code = cli_skills_extract.run(["varde-toz", "x"], out, roots=[tmp_path])
    assert code == 2
    assert "skills reset" in out.stderr.getvalue()
