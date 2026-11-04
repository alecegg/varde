from pathlib import Path

from varde.setup.catalog import Skill, SkillFile
from varde.setup.sync.skills import OWNERSHIP_MARKER, install_canonical
from varde_core import skill_props


def _skill(text: bytes = b"v1", ref: bytes = b"r1") -> Skill:
    return Skill(
        "varde-x",
        (SkillFile("SKILL.md", text, False), SkillFile("references/a.md", ref, False)),
    )


def _props(root: Path) -> skill_props.Props:
    return skill_props.parse((root / "varde-x" / OWNERSHIP_MARKER).read_text())


def test_fresh_install_writes_properties(tmp_path):
    install_canonical(tmp_path, (_skill(),))
    props = _props(tmp_path)
    expected = skill_props.tree_hash({"SKILL.md": b"v1", "references/a.md": b"r1"})
    assert props.packaged_hash == expected
    assert props.packaged_version
    assert not props.pending_hash


def test_unmodified_skill_is_replaced_and_refreshed(tmp_path):
    install_canonical(tmp_path, (_skill(),))
    messages = install_canonical(tmp_path, (_skill(b"v2"),))
    assert (tmp_path / "varde-x" / "SKILL.md").read_bytes() == b"v2"
    assert messages == [f"Installed skill varde-x -> {tmp_path / 'varde-x'}"]
    props = _props(tmp_path)
    assert props.packaged_hash == skill_props.tree_hash(
        {"SKILL.md": b"v2", "references/a.md": b"r1"}
    )
    assert not props.pending_hash


def test_pycache_does_not_count_as_modification(tmp_path):
    install_canonical(tmp_path, (_skill(),))
    cache = tmp_path / "varde-x" / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_bytes(b"junk")
    install_canonical(tmp_path, (_skill(b"v2"),))
    assert (tmp_path / "varde-x" / "SKILL.md").read_bytes() == b"v2"


def test_edited_files_survive_sync_and_pending_is_recorded(tmp_path):
    install_canonical(tmp_path, (_skill(),))
    (tmp_path / "varde-x" / "SKILL.md").write_bytes(b"mine")
    messages = install_canonical(tmp_path, (_skill(b"v2"),))
    assert (tmp_path / "varde-x" / "SKILL.md").read_bytes() == b"mine"
    assert messages == [
        (
            "Kept locally modified skill varde-x; "
            "packaged update pending (varde learn skills updates)"
        )
    ]
    props = _props(tmp_path)
    assert props.pending_hash == skill_props.tree_hash(
        {"SKILL.md": b"v2", "references/a.md": b"r1"}
    )
    assert props.pending_version
    install_canonical(tmp_path, (_skill(b"v2"),))
    assert (tmp_path / "varde-x" / "SKILL.md").read_bytes() == b"mine"
    assert _props(tmp_path) == props


def test_edited_reference_survives(tmp_path):
    install_canonical(tmp_path, (_skill(),))
    (tmp_path / "varde-x" / "references" / "a.md").write_bytes(b"mine")
    install_canonical(tmp_path, (_skill(ref=b"r2"),))
    assert (tmp_path / "varde-x" / "references" / "a.md").read_bytes() == b"mine"


def test_no_pending_when_packaged_hash_unchanged(tmp_path):
    install_canonical(tmp_path, (_skill(),))
    (tmp_path / "varde-x" / "SKILL.md").write_bytes(b"mine")
    install_canonical(tmp_path, (_skill(),))
    assert not _props(tmp_path).pending_hash


def test_install_before_properties_is_replaced_even_when_tree_differs(tmp_path):
    directory = tmp_path / "varde-x"
    directory.mkdir()
    (directory / OWNERSHIP_MARKER).write_text("varde-managed-skill\n")
    (directory / "SKILL.md").write_bytes(b"old")
    messages = install_canonical(tmp_path, (_skill(),))
    assert (directory / "SKILL.md").read_bytes() != b"old"
    assert messages[0].startswith("Installed skill varde-x")
    props = _props(tmp_path)
    assert props.packaged_hash and not props.pending_hash


def test_eval_runs_and_workspaces_do_not_count_as_modification(tmp_path):
    install_canonical(tmp_path, (_skill(),))
    directory = tmp_path / "varde-x"
    (directory / "evals").mkdir()
    (directory / "evals" / "run.json").write_text("{}")
    (directory / "iter-workspace").mkdir()
    (directory / "iter-workspace" / "out.md").write_text("x")
    messages = install_canonical(tmp_path, (_skill(b"v2"),))
    assert messages[0].startswith("Installed skill varde-x")


def test_install_before_properties_is_replaced_when_tree_matches(tmp_path):
    directory = tmp_path / "varde-x"
    (directory / "references").mkdir(parents=True)
    (directory / OWNERSHIP_MARKER).write_text("varde-managed-skill\n")
    (directory / "SKILL.md").write_bytes(b"v1")
    (directory / "references" / "a.md").write_bytes(b"r1")
    install_canonical(tmp_path, (_skill(),))
    assert _props(tmp_path).packaged_hash


def test_dry_run_writes_nothing(tmp_path):
    install_canonical(tmp_path, (_skill(),))
    (tmp_path / "varde-x" / "SKILL.md").write_bytes(b"mine")
    before = (tmp_path / "varde-x" / OWNERSHIP_MARKER).read_text()
    messages = install_canonical(tmp_path, (_skill(b"v2"),), dry_run=True)
    assert messages == ["would keep locally modified skill varde-x"]
    assert (tmp_path / "varde-x" / OWNERSHIP_MARKER).read_text() == before
    assert (tmp_path / "varde-x" / "SKILL.md").read_bytes() == b"mine"


def test_foreign_directory_is_preserved(tmp_path):
    directory = tmp_path / "varde-x"
    directory.mkdir()
    (directory / "mine").write_text("keep")
    messages = install_canonical(tmp_path, (_skill(),))
    assert messages == [f"Preserved unowned {directory}"]
    assert (directory / "mine").read_text() == "keep"
