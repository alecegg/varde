"""`skills updates`: state of synced skills and the diff to the packaged copy."""

from __future__ import annotations

import io
import json

import pytest
from varde_core import skill_props
from varde_learn.loop import cli_skills_updates
from varde_learn.loop.improve import skill_updates, tool_entry

NO_SYNC = "no sync target; run varde setup sync"


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


def _props(loop_hash: str = "", pending_hash: str = "") -> skill_props.Props:
    return skill_props.Props(
        packaged_hash="p", loop_hash=loop_hash, pending_hash=pending_hash
    )


def test_classify_each_state() -> None:
    assert skill_updates.classify(_props(), "p") == "clean"
    assert skill_updates.classify(_props(), "x") == "hand-modified"
    assert skill_updates.classify(_props(loop_hash="x"), "x") == "loop-modified"
    assert skill_updates.classify(_props(loop_hash="x"), "y") == "hand-modified"
    pending = _props(pending_hash="n", loop_hash="x")
    assert skill_updates.classify(pending, "x") == "update-pending"


def test_diff_direction_is_local_to_packaged() -> None:
    diff = skill_updates.diff_to_packaged(
        {"a.md": "local\n", "gone.md": "x\n"}, {"a.md": "packaged\n", "new.md": "n\n"}
    )
    assert "-local\n+packaged\n" in diff
    assert "--- /dev/null\n+++ new.md" in diff
    assert "-x\n" in diff
    assert skill_updates.diff_to_packaged({"a": "t\n"}, {"a": "t\n"}) == ""


def _install(sync, name, text, props: skill_props.Props) -> None:
    directory = sync / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(text)
    sidecar = skill_props.render(props)
    (directory / skill_props.SIDECAR).write_text(sidecar)


@pytest.fixture
def world(tmp_path, monkeypatch):
    state: dict = {}
    monkeypatch.setattr(tool_entry.memory_dirs, "load_config_document", lambda: state)
    sync = tmp_path / "sync"
    pkg = tmp_path / "pkg"
    (pkg / "skills" / "varde-a").mkdir(parents=True)
    (pkg / "skills" / "varde-a" / "SKILL.md").write_text("packaged\n")
    clean_hash = skill_props.tree_hash({"SKILL.md": b"packaged\n"})
    clean = skill_props.Props(packaged_hash=clean_hash, packaged_version="1")
    pending = skill_props.Props(
        packaged_hash=clean_hash, pending_hash="n", pending_version="2"
    )
    _install(sync, "varde-a", "packaged\n", clean)
    _install(sync, "varde-b", "local\n", pending)
    state["sync"] = {"skills_dir": str(sync)}
    return sync, pkg


def _snapshot(sync) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in sorted(sync.rglob("*")) if p.is_file()}


def test_list_shows_states_and_changes_nothing(world) -> None:
    sync, pkg = world
    before = _snapshot(sync)
    out = Io()
    assert cli_skills_updates.run([], out, roots=[pkg]) == 0
    assert out.stdout.getvalue() == "varde-a  clean\nvarde-b  update-pending\n"
    assert _snapshot(sync) == before


def test_list_json_shape(world) -> None:
    _, pkg = world
    out = Io()
    assert cli_skills_updates.run(["--json"], out, roots=[pkg]) == 0
    rows = json.loads(out.stdout.getvalue())["data"]["skills"]
    assert rows[1] == {
        "skill": "varde-b",
        "state": "update-pending",
        "packaged_version": "",
        "pending_version": "2",
    }


def test_one_skill_prints_diff_to_packaged(world) -> None:
    sync, pkg = world
    (pkg / "skills" / "varde-b").mkdir()
    (pkg / "skills" / "varde-b" / "SKILL.md").write_text("newer\n")
    before = _snapshot(sync)
    out = Io()
    assert cli_skills_updates.run(["varde-b"], out, roots=[pkg]) == 0
    assert "-local\n+newer\n" in out.stdout.getvalue()
    assert _snapshot(sync) == before
    clean = Io()
    assert cli_skills_updates.run(["varde-a", "--json"], clean, roots=[pkg]) == 0
    data = json.loads(clean.stdout.getvalue())["data"]
    assert data["state"] == "clean" and data["diff"] == ""


def test_unknown_skill_and_missing_target(world) -> None:
    out = Io()
    assert cli_skills_updates.run(["nope"], out) == 2
    assert "skill not installed: nope" in out.stderr.getvalue()
    del tool_entry.memory_dirs.load_config_document()["sync"]
    none = Io()
    assert cli_skills_updates.run([], none) == 2
    assert NO_SYNC in none.stderr.getvalue()
