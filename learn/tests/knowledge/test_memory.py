from types import SimpleNamespace

import pytest
import tomlkit
from varde_learn.knowledge import memory


def test_builtin_paths_and_config_exports(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(memory, "config_path", lambda: tmp_path / "config.toml")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.delenv("VARDE_WORKING_DIR", raising=False)
    monkeypatch.delenv("VARDE_KNOWLEDGE_DIR", raising=False)
    paths = memory.MemoryPaths.resolve_with(tmp_path / "app", tomlkit.parse(""))
    key = paths.working.path.parent
    assert key.parent == tmp_path / "share" / "varde" / "projects"
    assert key.name.startswith("app-")
    assert paths.working.path == key / "working"
    assert paths.knowledge.path == key / "knowledge"
    assert paths.working.source is memory.Source.BUILTIN
    assert paths.config == tmp_path / "config.toml"


def test_precedence_and_expansion(monkeypatch, tmp_path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(memory.WORKING_ENV, "~/env/{project}")
    config = tomlkit.parse(
        '[default]\nworking = "~/default/{project}"\nknowledge = "docs"\n\n[project."'
        + str(root)
        + '"]\nworking = "project-work"\n'
    )
    paths = memory.MemoryPaths.resolve_with(root, config)
    assert paths.working == memory.Resolved(
        (tmp_path / "env/app").resolve(), memory.Source.ENV
    )
    assert paths.knowledge == memory.Resolved(
        (root / "docs").resolve(), memory.Source.DEFAULT
    )


def test_worktree_paths_keep_checkout_and_share_repository_root(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    import subprocess

    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "tracked").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "tracked"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )
    checkout = tmp_path / "checkout"
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "worktree",
            "add",
            "-q",
            "-b",
            "linked",
            str(checkout),
        ],
        check=True,
    )
    paths = memory.MemoryPaths.resolve_with(checkout, tomlkit.parse(""))
    assert paths.root == repo
    assert paths.checkout_root == checkout
    assert memory.repository_memory_root(checkout) == repo


def test_find_root_uses_git_root_and_has_no_memory_bank_fallback(
    monkeypatch,
    tmp_path,
) -> None:
    import subprocess

    repo = tmp_path / "repo"
    nested = repo / "module"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setattr(
        memory, "load_config", lambda: SimpleNamespace(document=tomlkit.parse(""))
    )
    assert memory.find_root(nested) == repo
    outside = tmp_path / "outside"
    (outside / "memory-bank").mkdir(parents=True)
    (outside / "nested").mkdir()
    assert memory.find_root(outside / "nested") is None


def test_find_root_prefers_configured_project_to_git_root(
    monkeypatch, tmp_path
) -> None:
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    working = repo / "memory-bank" / "working"
    working.mkdir(parents=True)
    config = tomlkit.parse(f'[project."{repo}"]\nworking = "memory-bank/working"\n')
    monkeypatch.setattr(memory, "load_config", lambda: SimpleNamespace(document=config))
    assert memory.find_root(working) == repo


def test_write_roots_collapse_nested_and_contains(tmp_path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    paths = memory.MemoryPaths.resolve_with(
        root,
        tomlkit.parse(
            '[default]\nworking = "memory-bank/working"\n'
            'knowledge = "memory-bank/knowledge"\n'
        ),
    )
    assert paths.write_roots() == [root, paths.memory.path]
    assert paths.contains(root / "memory-bank/knowledge/note.md")
    assert not paths.contains(tmp_path / "other")


def test_blank_configured_learn_path_fails(tmp_path) -> None:
    with pytest.raises(ValueError, match="default.learn"):
        memory.MemoryPaths.resolve_with(
            tmp_path, tomlkit.parse('[default]\nlearn = " "\n')
        )


def test_memory_kind_resolution(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(memory, "config_path", lambda: tmp_path / "config.toml")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.delenv(memory.MEMORY_ENV, raising=False)
    paths = memory.MemoryPaths.resolve_with(tmp_path / "app", tomlkit.parse(""))
    assert paths.memory.path == tmp_path / "share" / "varde" / "memory"
    assert paths.get("memory") is paths.memory
    assert paths.memory.path in paths.write_roots()
    monkeypatch.setenv(memory.MEMORY_ENV, str(tmp_path / "env"))
    paths = memory.MemoryPaths.resolve_with(tmp_path / "app", tomlkit.parse(""))
    assert paths.memory == memory.Resolved(tmp_path / "env", memory.Source.ENV)
