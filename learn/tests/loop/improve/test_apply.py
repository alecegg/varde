from __future__ import annotations

import io

import pytest
from varde_learn.loop import cli_skills_accept, cli_skills_extract, cli_skills_reject
from varde_learn.loop.improve import apply, filediff
from varde_learn.loop.improve import record as rec
from varde_learn.memory import store

TOPIC = (
    "---\ntopic: varde-x/do\nversion: 1\nsummary: S\n---\n\n"
    "Step one is to read the input files and list what changed in each.\n"
    "Step two covers every changed file in turn with a short summary.\n"
)


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


def accept(pkg, record_id, out=None) -> int:
    return cli_skills_accept.run([record_id], out or Io(), roots=[pkg])


@pytest.fixture
def world(tmp_path, monkeypatch):
    pkg = tmp_path / "pkg"
    topic = pkg / "how" / "varde-x" / "do.md"
    topic.parent.mkdir(parents=True)
    topic.write_text(TOPIC)
    memory = tmp_path / "memory"
    monkeypatch.setattr(store, "memory_root", lambda _cwd: memory)
    code = cli_skills_extract.run(["varde-x", "do"], Io(), roots=[pkg])
    assert code == 0
    [record] = rec.list_records(memory)
    return pkg, memory, record


def test_accept_applies_diff_and_records_state(world, approve) -> None:
    pkg, memory, record = world
    approve(memory, record.id)
    out = Io()
    assert accept(pkg, record.id, out) == 0
    assert out.stdout.getvalue().startswith("token delta -")
    assert 'step-tool" varde-x/do' in (pkg / "how/varde-x/do.md").read_text()
    assert (pkg / "step_tools/varde-x/do.py").is_file()
    assert (pkg / "step_tools/registry.toml").is_file()
    assert rec.read_record(memory, record.id).state == "applied"


def test_accept_refuses_when_edited_since_and_changes_nothing(world, approve) -> None:
    pkg, memory, record = world
    approve(memory, record.id)
    topic = pkg / "how/varde-x/do.md"
    topic.write_text(TOPIC + "edited\n")
    out = Io()
    assert accept(pkg, record.id, out) == 2
    assert "changed since proposed" in out.stderr.getvalue()
    assert topic.read_text() == TOPIC + "edited\n"
    assert not (pkg / "step_tools").exists()
    assert rec.read_record(memory, record.id).state == "proposed"


def test_accept_refuses_when_new_file_already_exists(world, approve) -> None:
    pkg, memory, record = world
    approve(memory, record.id)
    (pkg / "step_tools/varde-x").mkdir(parents=True)
    (pkg / "step_tools/varde-x/do.py").write_text("x = 1\n")
    assert accept(pkg, record.id) == 2
    assert (pkg / "step_tools/varde-x/do.py").read_text() == "x = 1\n"


def test_reject_marks_proposed_and_changes_no_file(world, approve) -> None:
    pkg, memory, record = world
    approve(memory, record.id)
    before = (pkg / "how/varde-x/do.md").read_text()
    assert cli_skills_reject.run([record.id], Io()) == 0
    assert rec.read_record(memory, record.id).state == "rejected"
    assert (pkg / "how/varde-x/do.md").read_text() == before
    assert accept(pkg, record.id) == 2


def test_reject_on_applied_refuses_and_changes_nothing(world, approve) -> None:
    pkg, memory, record = world
    approve(memory, record.id)
    accept(pkg, record.id)
    after = (pkg / "how/varde-x/do.md").read_text()
    out = Io()
    assert cli_skills_reject.run([record.id], out) == 2
    assert "no undo" in out.stderr.getvalue()
    assert rec.read_record(memory, record.id).state == "applied"
    assert (pkg / "how/varde-x/do.md").read_text() == after


def test_unknown_id_and_usage(world) -> None:
    assert cli_skills_accept.run(["nope"], Io()) == 2
    assert cli_skills_accept.run([], Io()) == 2
    assert cli_skills_reject.run(["a", "b"], Io()) == 2


def test_pure_hash_check_and_post_images() -> None:
    hashes = {"/a": rec.hash_text("x\n"), "/new": filediff.ABSENT}
    assert apply.stale_paths(hashes, {"/a": "x\n", "/new": None}) == []
    assert apply.stale_paths(hashes, {"/a": "y\n", "/new": "z"}) == ["/a", "/new"]
    diff = filediff.make_file_diff("/a", "x\n", "w\n") + filediff.make_file_diff(
        "/new", None, "n\n"
    )
    assert apply.post_images(diff, {"/a": "x\n", "/new": None}) == {
        "/a": "w\n",
        "/new": "n\n",
    }
    with pytest.raises(apply.ApplyError):
        apply.post_images(diff, {"/a": "x\n", "/new": "exists"})
    assert apply.touches_agent_source(["/r/agents/capabilities.json"])
    assert apply.touches_agent_source(["/r/app/templates/claude.md.tpl"])
    assert not apply.touches_agent_source(["/r/how/a.md"])
