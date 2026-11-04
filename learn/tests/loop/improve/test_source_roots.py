"""Skill edits land in the synced skill at the sync target, never a package copy."""

from __future__ import annotations

import io

import pytest
from varde_core import skill_props
from varde_learn.loop import (
    cli_skills_accept,
    cli_skills_candidates,
    cli_skills_extract,
    cli_skills_reset,
)
from varde_learn.loop.improve import apply, extract, skill_updates, tool_entry
from varde_learn.loop.improve import record as rec
from varde_learn.memory import store

NO_SYNC = "no sync target; run varde setup sync"


def _topic(step: str) -> str:
    return (
        f"---\ntopic: varde-x/{step}\nversion: 1\nsummary: S\n---\n\n"
        "Step one is to read the input files and list what changed in each.\n"
        "Step two covers every changed file in turn with a short summary.\n"
    )


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


@pytest.fixture
def world(tmp_path, monkeypatch):
    state: dict = {}
    monkeypatch.setattr(tool_entry.memory_dirs, "load_config_document", lambda: state)
    sync = tmp_path / "sync"
    skill = sync / "varde-x"
    (skill / "how").mkdir(parents=True)
    (skill / "SKILL.md").write_text("# varde-x\n")
    (skill / "how" / "do.md").write_text(_topic("do"))
    (skill / "how" / "two.md").write_text(_topic("two"))
    packaged = skill_props.tree_hash(skill_props.disk_tree(skill))
    sidecar = skill_props.render(skill_props.Props(packaged_hash=packaged))
    (skill / skill_props.SIDECAR).write_text(sidecar)
    state["sync"] = {"skills_dir": str(sync)}
    memory = tmp_path / "memory"
    monkeypatch.setattr(store, "memory_root", lambda _cwd: memory)
    return sync, skill, memory, packaged


def _propose(step: str) -> int:
    return cli_skills_extract.run(["varde-x", step], Io())


def test_accepted_extract_writes_at_sync_target_and_updates_sidecar(
    world, approve
) -> None:
    _sync, skill, memory, packaged = world
    assert _propose("do") == 0
    [record] = rec.list_records(memory)
    diff = rec.read_diff(memory, record)
    assert "cli-releases" not in diff and "site-packages" not in diff
    approve(memory, record.id)
    assert cli_skills_accept.run([record.id], Io()) == 0
    assert (skill / "step_tools" / "varde-x" / "do.py").is_file()
    assert (skill / "step_tools" / "registry.toml").is_file()
    found = tool_entry.find_tool([skill], "varde-x", "do")
    assert found is not None and found[0] == skill
    props = skill_props.parse((skill / skill_props.SIDECAR).read_text())
    assert props.loop_hash == skill_props.tree_hash(skill_props.disk_tree(skill))
    assert props.packaged_hash == packaged
    assert props.loop_hash != packaged


def test_second_proposal_builds_on_accepted_text(world, approve) -> None:
    _sync, skill, memory, _ = world
    assert _propose("do") == 0
    [first] = rec.list_records(memory)
    approve(memory, first.id)
    assert cli_skills_accept.run([first.id], Io()) == 0
    assert _propose("two") == 0
    [second] = [r for r in rec.list_records(memory) if r.id != first.id]
    registry = skill / "step_tools" / "registry.toml"
    assert second.pre_hashes[str(registry)] == rec.hash_text(registry.read_text())


def test_accept_refuses_package_root_paths(world, approve, tmp_path) -> None:
    _sync, _skill, memory, _ = world
    pkg = tmp_path / "pkg"
    topic = pkg / "how" / "varde-x" / "do.md"
    topic.parent.mkdir(parents=True)
    topic.write_text(_topic("do"))
    assert cli_skills_extract.run(["varde-x", "do"], Io(), roots=[pkg]) == 0
    [record] = rec.list_records(memory)
    approve(memory, record.id)
    with pytest.raises(apply.ApplyError, match="outside the installed skill directory"):
        apply.accept(memory, record.id)
    assert topic.read_text() == _topic("do")


def test_accept_refuses_agent_source(world, approve, tmp_path) -> None:
    _sync, _skill, memory, _ = world
    caps = tmp_path / "pkg" / "agents" / "capabilities.json"
    caps.parent.mkdir(parents=True)
    caps.write_text('{"profiles": []}\n')
    changes = (
        extract.FileChange(str(caps), '{"profiles": []}\n', '{"profiles": [1]}\n'),
    )
    record = rec.LoopRecord(
        id="forged-agent",
        skill="varde-x",
        direction="trim",
        change="forged",
        created="2026-11-02T00:00:00+00:00",
        pre_hashes=extract.pre_hashes(changes),
    )
    rec.write_record(memory, record, extract.render_diff(changes))
    approve(memory, record.id)
    with pytest.raises(apply.ApplyError, match="generated from the package"):
        apply.accept(memory, record.id)


def test_accept_refuses_foreign_skill_dir(world, approve) -> None:
    _sync, skill, memory, _ = world
    assert _propose("do") == 0
    [record] = rec.list_records(memory)
    approve(memory, record.id)
    (skill / skill_props.SIDECAR).unlink()
    with pytest.raises(apply.ApplyError, match="no sidecar"):
        apply.accept(memory, record.id)
    assert "step-tool" not in (skill / "how" / "do.md").read_text()


def test_verbs_need_a_sync_target(world, tmp_path) -> None:
    state_sync = tool_entry.memory_dirs.load_config_document()
    del state_sync["sync"]
    for run, args in (
        (cli_skills_extract.run, ["varde-x", "do"]),
        (cli_skills_reset.run, ["varde-x", "--model", "m", "--harness-version", "1"]),
        (cli_skills_candidates.run, []),
        (cli_skills_accept.run, ["any-id"]),
    ):
        out = Io()
        assert run(args, out) == 2, run
        assert NO_SYNC in out.stderr.getvalue()


def test_reset_slims_the_synced_skill(world) -> None:
    _sync, skill, _memory, _ = world
    text = "# varde-x\n\n## Intro\n\nShort.\n\n## Details\n\n" + "word " * 400 + "\n"
    (skill / "SKILL.md").write_text(text)
    args = ["varde-x", "--model", "m", "--harness-version", "1", "--dry-run"]
    out = Io()
    code = cli_skills_reset.run(args, out, demand=lambda _n: {"steps": []})
    assert code == 0, out.stderr.getvalue()
    assert str(skill / "SKILL.md") in out.stdout.getvalue()


def test_hand_edits_before_accept_stay_hand_modified(world, approve) -> None:
    _sync, skill, memory, _ = world
    (skill / "references").mkdir()
    (skill / "references" / "mine.md").write_text("hand edit\n")
    assert _propose("do") == 0
    [record] = rec.list_records(memory)
    approve(memory, record.id)
    assert cli_skills_accept.run([record.id], Io()) == 0
    props = skill_props.parse((skill / skill_props.SIDECAR).read_text())
    assert props.loop_hash == ""
    current = skill_props.tree_hash(skill_props.disk_tree(skill))
    assert skill_updates.classify(props, current) == "hand-modified"


def test_symlinked_sidecar_is_not_a_synced_skill(world) -> None:
    sync, skill, _memory, _ = world
    real = skill.parent / "real-sidecar"
    real.write_text("varde-managed-skill\n")
    (skill / skill_props.SIDECAR).unlink()
    (skill / skill_props.SIDECAR).symlink_to(real)
    assert tool_entry.installed_skill(sync, "varde-x") is None
