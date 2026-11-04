"""Tests for per-project memory directory resolution."""

from varde_core.memory_dirs import (
    default_memory_dir,
    legacy_memory_bank_dirs,
    resolve_memory_dir,
    resolve_project_dir,
)
from varde_core.paths import fnv1a64, local_share_dir


def test_fnv1a64_known_value() -> None:
    assert fnv1a64(b"") == 0xCBF29CE484222325
    assert fnv1a64(b"a") == 0xAF63DC4C8601EC8C


def test_local_share_dir_prefers_absolute_xdg(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert local_share_dir() == tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", "relative")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert local_share_dir() == tmp_path / ".local" / "share"


def test_default_dir_is_outside_repo_and_keyed_by_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    first = tmp_path / "a" / "api"
    second = tmp_path / "b" / "api"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    one = default_memory_dir(first, "working")
    assert one.parent.name.startswith("api-")
    assert len(one.parent.name) == len("api-") + 16
    assert one.parts[-4:-2] == ("varde", "projects")
    assert one != default_memory_dir(second, "working")
    assert one == default_memory_dir(first, "working")
    assert default_memory_dir(first, "knowledge").name == "knowledge"
    assert not one.is_relative_to(first)


def test_resolve_precedence(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.delenv("VARDE_WORKING_DIR", raising=False)
    root = tmp_path / "app"
    root.mkdir()
    assert resolve_memory_dir(root, "working", {})[1] == "builtin"
    document = {
        "default": {"working": "dflt"},
        "project": {str(root): {"working": "p"}},
    }
    assert resolve_memory_dir(root, "working", document) == (root / "p", "project")
    assert resolve_memory_dir(root, "working", {"default": {"working": "d"}}) == (
        root / "d",
        "default",
    )
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path / "env"))
    assert resolve_memory_dir(root, "working", document) == (tmp_path / "env", "env")


def test_resolve_project_dir_honors_config(monkeypatch, tmp_path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    config = tmp_path / "cfg"
    config.mkdir()
    (config / "config.toml").write_text(f'[project."{root}"]\nknowledge = "k"\n')
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.delenv("VARDE_KNOWLEDGE_DIR", raising=False)
    assert resolve_project_dir(root, "knowledge") == root / "k"


def test_legacy_memory_bank_dirs(tmp_path) -> None:
    assert legacy_memory_bank_dirs(tmp_path) == []
    (tmp_path / "memory-bank" / "working").mkdir(parents=True)
    assert legacy_memory_bank_dirs(tmp_path) == [tmp_path / "memory-bank" / "working"]


def test_expand_tilde_prefix_strips_only_leading_tilde_slash(
    monkeypatch, tmp_path
) -> None:
    from varde_core.memory_dirs import expand

    monkeypatch.setenv("HOME", str(tmp_path))
    assert expand(tmp_path / "r", "~/~x") == tmp_path / "~x"
    assert expand(tmp_path / "r", "~") == tmp_path


def test_local_share_dir_without_home_is_absolute(monkeypatch) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.setattr(
        "varde_core.paths.Path.home", lambda: (_ for _ in ()).throw(RuntimeError())
    )
    assert local_share_dir().is_absolute()


def test_memory_kind_defaults_and_overrides(monkeypatch, tmp_path) -> None:
    from varde_core.memory_dirs import KINDS, LEGACY_KINDS

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.delenv("VARDE_MEMORY_DIR", raising=False)
    root = tmp_path / "app"
    root.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    builtin = tmp_path / "share" / "varde" / "memory"
    assert KINDS == ("working", "knowledge", "memory")
    assert LEGACY_KINDS == ("working", "knowledge")
    assert resolve_memory_dir(root, "memory", {}) == (builtin, "builtin")
    assert resolve_memory_dir(other, "memory", {}) == (builtin, "builtin")
    assert default_memory_dir(root, "memory") == builtin
    default = {"default": {"memory": str(tmp_path / "dflt")}}
    assert resolve_memory_dir(root, "memory", default) == (tmp_path / "dflt", "default")
    monkeypatch.setenv("VARDE_MEMORY_DIR", str(tmp_path / "env"))
    assert resolve_memory_dir(root, "memory", default) == (tmp_path / "env", "env")


def test_project_table_is_ignored_for_memory_kind(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.delenv("VARDE_MEMORY_DIR", raising=False)
    root = tmp_path / "app"
    root.mkdir()
    builtin = tmp_path / "share" / "varde" / "memory"
    for value in (str(tmp_path / "abs"), "rel"):
        document = {"project": {str(root): {"memory": value}}}
        assert resolve_memory_dir(root, "memory", document) == (builtin, "builtin")
    relative = {"default": {"memory": "rel"}}
    assert resolve_memory_dir(root, "memory", relative) == (root / "rel", "default")


def test_project_key_matches_default_dir_key(monkeypatch, tmp_path) -> None:
    from varde_core.memory_dirs import project_key

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    root = tmp_path / "My Repo_X"
    root.mkdir()
    key = project_key(root)
    assert key.startswith("My Repo_X-") and len(key) == len("My Repo_X-") + 16
    assert default_memory_dir(root, "working") == (
        tmp_path / "share" / "varde" / "projects" / key / "working"
    )


def test_legacy_memory_bank_ignores_memory_dir(tmp_path) -> None:
    (tmp_path / "memory-bank" / "memory").mkdir(parents=True)
    assert legacy_memory_bank_dirs(tmp_path) == []
    (tmp_path / "memory-bank" / "working").mkdir()
    assert legacy_memory_bank_dirs(tmp_path) == [tmp_path / "memory-bank" / "working"]
