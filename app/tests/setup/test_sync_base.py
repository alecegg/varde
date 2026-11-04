from pathlib import Path

import pytest
from varde.setup.sync.config import read, validate_skills, write
from varde.setup.sync.fsops import (
    copy_directory,
    remove_path,
    replace_directory,
    replace_file,
    replace_with_copy,
    replace_with_file_symlink,
    replace_with_symlink,
    write_file,
)
from varde.setup.sync.harness import HarnessId, detect, select
from varde_learn.knowledge.memory_config import Config


def test_read_missing_sync_defaults():
    assert read(Config()).skills_dir is None


def test_read_sync_must_be_table():
    with pytest.raises(ValueError, match="must be a table"):
        read(Config({"sync": "bad"}))


def test_read_skills_dir_path():
    assert read(Config({"sync": {"skills_dir": "skills"}})).skills_dir == Path("skills")


def test_read_agents_dir_path():
    assert read(Config({"sync": {"agents_dir": "agents"}})).agents_dir == Path("agents")


def test_read_link_mode():
    assert read(Config({"sync": {"link_mode": "copy"}})).link_mode == "copy"


@pytest.mark.parametrize("key", ["skills_dir", "agents_dir"])
def test_read_path_must_be_string(key):
    with pytest.raises(ValueError, match="must be a string"):
        read(Config({"sync": {key: 3}}))


def test_read_link_mode_must_be_string():
    with pytest.raises(ValueError, match="link_mode must be a string"):
        read(Config({"sync": {"link_mode": 4}}))


def test_read_skills_list():
    assert read(Config({"sync": {"skills": ["varde-code"]}})).skills == ["varde-code"]


@pytest.mark.parametrize("value", ["varde-code", [1]])
def test_read_skills_must_be_string_array(value):
    with pytest.raises(ValueError, match="array of strings"):
        read(Config({"sync": {"skills": value}}))


def test_read_unknown_skill_is_rejected():
    with pytest.raises(ValueError, match="unknown skill"):
        read(Config({"sync": {"skills": ["no-such-skill"]}}))


def test_write_settings_preserves_unrelated_config():
    config = Config({"other": {"value": 1}})
    write(config, Path("skills"), Path("agents"), "copy")
    assert config.document["other"] == {"value": 1}


def test_write_settings_preserves_unknown_sync_key():
    config = Config({"sync": {"custom": True}})
    write(config, Path("skills"), Path("agents"), "copy")
    assert config.document["sync"]["custom"] is True


def test_write_settings_serializes_paths(tmp_path):
    config = Config()
    skills = tmp_path / "skills"
    agents = tmp_path / "agents"
    write(config, skills, agents, "symlink")
    assert config.document["sync"]["skills_dir"] == str(skills)


def test_write_selected_skills():
    config = Config()
    write(config, Path("s"), Path("a"), "copy", ["varde-code"])
    assert config.document["sync"]["skills"] == ["varde-code"]


def test_write_empty_selection_removes_saved_skills():
    config = Config({"sync": {"skills": ["varde-code"]}})
    write(config, Path("s"), Path("a"), "copy", [])
    assert "skills" not in config.document["sync"]


def test_validate_skills_accepts_catalog_skill():
    validate_skills(["varde-code"])


def test_harness_ids_parse_and_reject_unknown():
    assert HarnessId.parse("claude") is HarnessId.CLAUDE
    with pytest.raises(ValueError, match="unknown harness id"):
        HarnessId.parse("unknown")


def test_harness_detection_and_pi_override(tmp_path):
    (tmp_path / ".claude").mkdir()
    found = detect(tmp_path, tmp_path / "pi-home")
    assert [item.id for item in found] == [HarnessId.CLAUDE, HarnessId.PI]
    assert found[-1].agents_dir == tmp_path / "pi-home/agents"


def test_harness_selection_is_canonical_order(tmp_path):
    found = select([HarnessId.PI, HarnessId.CLAUDE], tmp_path)
    assert [item.id for item in found] == [HarnessId.CLAUDE, HarnessId.PI]


def test_copy_directory_copies_regular_tree(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "item").write_text("data")
    copy_directory(source, tmp_path / "out")
    assert (tmp_path / "out/item").read_text() == "data"


def test_copy_directory_refuses_symlinks(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "link").symlink_to(tmp_path)
    with pytest.raises(OSError, match="refusing to copy"):
        copy_directory(source, tmp_path / "out")


def test_copy_directory_requires_real_directory(tmp_path):
    file = tmp_path / "file"
    file.write_text("x")
    with pytest.raises(OSError, match="not a real directory"):
        copy_directory(file, tmp_path / "out")


def test_write_file_sets_non_executable_mode(tmp_path):
    path = tmp_path / "nested/file"
    write_file(path, b"hello")
    assert path.read_text(encoding="utf-8") == "hello"
    assert path.stat().st_mode & 0o111 == 0


def test_replace_file_replaces_existing_file(tmp_path):
    path = tmp_path / "file"
    path.write_text("old")
    replace_file(path, b"new")
    assert path.read_text(encoding="utf-8") == "new"


def test_replace_directory_replaces_existing_tree(tmp_path):
    path = tmp_path / "tree"
    path.mkdir()
    (path / "old").touch()
    replace_directory(path, lambda staged: (staged / "new").touch())
    assert sorted(p.name for p in path.iterdir()) == ["new"]


def test_replace_with_copy_replaces_tree(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file").write_text("copy")
    replace_with_copy(tmp_path / "dst", src)
    assert (tmp_path / "dst/file").read_text() == "copy"


def test_replace_with_directory_symlink(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    dest = tmp_path / "dest"
    replace_with_symlink(dest, source)
    assert dest.is_symlink() and dest.resolve() == source


def test_replace_with_file_symlink(tmp_path):
    source = tmp_path / "src"
    source.write_text("target")
    dest = tmp_path / "dest"
    replace_with_file_symlink(dest, source)
    assert dest.is_symlink() and dest.read_text() == "target"


def test_remove_path_handles_missing_and_symlink(tmp_path):
    missing = tmp_path / "missing"
    remove_path(missing)
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    remove_path(link)
    assert target.is_dir() and not link.exists()
