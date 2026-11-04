from multiprocessing import Process
from pathlib import Path

import pytest
from varde_data.config import DataConfig
from varde_data.errors import GitStorePath, Invalid
from varde_data.open import open_data
from varde_data.paths import (
    git_command,
    reject_git_path,
    resolve_directory,
    resolve_learn_store,
)


def _git_init(path: Path, bare: bool = False) -> None:
    import subprocess

    command = ["git", "init"]
    if bare:
        command.append("--bare")
    subprocess.run(  # noqa: S603 - fixed Git init command in a temporary test directory
        [*command, str(path)], check=True, capture_output=True
    )


def _init_repo(path: Path, *, bare: bool = False) -> None:
    process = Process(target=_git_init, args=(path, bare))
    process.start()
    process.join()
    assert process.exitcode == 0


def test_resolve_learn_store_prefers_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "from-env"))

    assert (
        resolve_learn_store(tmp_path / "config", {"default": {"learn": "other"}})
        == tmp_path / "from-env"
    )


def test_resolve_learn_store_uses_config_and_fallback(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("VARDE_LEARN_STORE", raising=False)
    assert (
        resolve_learn_store(tmp_path / "config", {"default": {"learn": "configured"}})
        == Path.cwd() / "configured"
    )
    assert resolve_learn_store(tmp_path / "config", {}) == tmp_path / "config" / "learn"


def test_open_data_uses_resolved_root_and_memory_backend(tmp_path: Path) -> None:
    root = tmp_path / "global-learn"
    friction = open_data(
        tmp_path / "working",
        DataConfig(backends={"friction": "memory"}, learn_store=root),
    ).friction

    assert friction.list_items().items == ()


def test_resolve_directory_keeps_missing_components_and_resolves_symlinks(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    assert resolve_directory(link / "new" / "store") == real / "new" / "store"


def test_resolve_directory_normalizes_parent_components(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()

    assert resolve_directory(target / "child" / ".." / "store") == target / "store"


def test_resolve_directory_anchors_relative_paths_to_current_directory(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    assert resolve_directory(Path("relative/../store")) == tmp_path / "store"


def test_resolve_learn_store_requires_home_for_tilde(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("VARDE_LEARN_STORE", raising=False)
    monkeypatch.delenv("HOME", raising=False)

    with pytest.raises(Invalid, match="HOME is unset"):
        resolve_learn_store(tmp_path, {"default": {"learn": "~/store"}})


def test_resolve_directory_rejects_symlink_loop(tmp_path: Path) -> None:
    left, right = tmp_path / "left", tmp_path / "right"
    left.symlink_to(right)
    right.symlink_to(left)

    with pytest.raises(Invalid):
        resolve_directory(left)


def test_reject_git_path_checks_learn_database_ignore_pattern(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    store = repo / "store"
    store.mkdir()
    database = store / "learn.db"

    with pytest.raises(GitStorePath):
        reject_git_path(database)

    (repo / ".gitignore").write_text("learn.db*\n")
    reject_git_path(database)


def test_reject_git_path_refuses_bare_repository(tmp_path: Path) -> None:
    repo = tmp_path / "bare.git"
    _init_repo(repo, bare=True)

    with pytest.raises(GitStorePath):
        reject_git_path(repo / "learn.db")


def test_git_command_scrubs_git_environment(monkeypatch, tmp_path: Path) -> None:
    import subprocess

    observed = {}

    def run(args, **kwargs):
        observed.update(kwargs["env"])
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("varde_data.paths.subprocess.run", run)
    for name in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_CEILING_DIRECTORIES",
    ):
        monkeypatch.setenv(name, str(tmp_path))

    git_command(["-C", str(tmp_path), "rev-parse"])

    assert (
        not {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES"}
        & observed.keys()
    )
