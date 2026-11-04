from multiprocessing import Process
from pathlib import Path

import pytest
from varde_learn.loop.errors import StoreInsideGit
from varde_learn.loop.store.paths import reject_git_path, work_tree_root


def _init_git(path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)


def _git_repo(path: Path) -> Path:
    path.mkdir()
    process = Process(target=_init_git, args=(path,))
    process.start()
    process.join()
    assert process.exitcode == 0
    return path


def test_reject_git_path_allows_paths_outside_repository(tmp_path: Path) -> None:
    path = tmp_path / "store"
    path.mkdir()

    assert reject_git_path(path) is None


def test_reject_git_path_refuses_unignored_store_and_allows_ignored(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path / "repo")
    store = repo / "store"
    store.mkdir()
    with pytest.raises(StoreInsideGit):
        reject_git_path(store / "learn.db")

    (repo / ".gitignore").write_text("learn.db*\n")
    reject_git_path(store / "learn.db")
    assert work_tree_root(store) == repo.resolve()


def test_reject_git_path_refuses_git_directory(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    with pytest.raises(StoreInsideGit):
        reject_git_path(repo / ".git" / "learn.db")


def test_validate_global_path_bootstraps_gitignore(tmp_path: Path) -> None:
    from varde_data.friction_events import ensure_git_files
    from varde_learn.loop.store.paths import validate_store_path

    repo = _git_repo(tmp_path / "repo")
    store = repo / "store"
    store.mkdir()

    validate_store_path(store)
    ensure_git_files(store)
    assert (store / ".gitignore").read_text().splitlines() == [
        "learn.db*",
        "learn.db.init.lock",
        "learn.sqlite3*",
        "store-mode.json",
        "store-mode.lock",
    ]


def test_validate_store_path_accepts_learn_database_ignore_pattern(
    tmp_path: Path,
) -> None:
    from varde_learn.loop.store.paths import validate_store_path

    repo = _git_repo(tmp_path / "repo")
    store = repo / "store"
    store.mkdir()
    (repo / ".gitignore").write_text("learn.db*\n")

    validate_store_path(store)
