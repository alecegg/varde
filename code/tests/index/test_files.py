from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from varde_code.index import files
from varde_code.index.files import (
    UNKNOWN_METADATA,
    DefaultFileWalker,
    is_vcs_internal,
    list_source_files,
    list_source_listing,
)


def test_lists_files_with_metadata_including_dotfiles_and_prunes_git(
    tmp_path: Path,
) -> None:
    (tmp_path / ".github").mkdir()
    visible = tmp_path / ".github" / "workflow.yml"
    visible.write_text("name: ci\n", encoding="utf-8")
    vcs = tmp_path / ".git" / "objects"
    vcs.mkdir(parents=True)
    (vcs / "pack").write_bytes(b"internal")

    listing = list_source_listing(tmp_path)

    assert [Path(file.path) for file in listing.files] == [visible]
    assert listing.files[0].mtime == visible.stat().st_mtime_ns
    assert listing.files[0].size == len(b"name: ci\n")
    assert listing.files[0].content_hash is None
    assert listing.diagnostics == []


def test_prunes_linked_worktrees_and_generated_directories(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pkg"
    (source / "build").mkdir(parents=True)
    visible = source / "build" / "main.py"
    visible.write_text("pass\n", encoding="utf-8")
    vendored = source / "vendor" / "lib.py"
    vendored.parent.mkdir()
    vendored.touch()
    (tmp_path / ".varde" / "other").mkdir(parents=True)
    other = tmp_path / ".varde" / "other" / "visible.py"
    other.touch()
    internal_scratch = tmp_path / ".varde" / ".scratch" / "generated.py"
    internal_scratch.parent.mkdir()
    internal_scratch.touch()
    worktree = tmp_path / "nested" / "checkout"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: ../.git/worktrees/checkout\n")
    (worktree / "generated.py").write_text("pass\n", encoding="utf-8")
    for directory in (
        ".varde/worktrees/task",
        ".scratch/tmp",
        ".venv/lib",
        "node_modules/pkg",
        "build/output",
        "target/debug",
    ):
        artifact = tmp_path / directory
        artifact.mkdir(parents=True)
        (artifact / "generated.py").write_text("pass\n", encoding="utf-8")

    listing = list_source_listing(tmp_path)

    assert sorted(Path(file.path) for file in listing.files) == sorted(
        [other, vendored, visible]
    )
    assert listing.diagnostics == []


def test_root_linked_worktree_and_submodule_are_walked(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: ../.git/worktrees/root\n")
    root_source = tmp_path / "root.py"
    root_source.touch()
    submodule = tmp_path / "deps" / "library"
    submodule.mkdir(parents=True)
    (submodule / ".git").write_text("gitdir: ../../.git/modules/library\n")
    submodule_source = submodule / "lib.py"
    submodule_source.touch()

    listing = list_source_listing(tmp_path)

    assert sorted(Path(file.path) for file in listing.files) == sorted(
        [root_source, submodule_source]
    )
    assert listing.diagnostics == []


def test_symlinked_directory_is_neither_followed_nor_diagnostic(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "hidden.py").touch()
    link = tmp_path / "linked"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks unavailable: {error}")

    listing = list_source_listing(tmp_path)

    assert listing.files == []
    assert listing.diagnostics == []


def test_single_file_input_and_missing_root(tmp_path: Path) -> None:
    file = tmp_path / "one.py"
    file.write_text("x = 1\n", encoding="utf-8")

    assert list_source_files(file) == list_source_listing(file).files
    with pytest.raises(FileNotFoundError, match="path does not exist"):
        list_source_listing(tmp_path / "missing")


def test_walker_reports_directory_errors_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    good = tmp_path / "good.py"
    good.write_text("ok", encoding="utf-8")
    real_scandir = os.scandir

    def scandir(path: str | bytes | os.PathLike[str] | os.PathLike[bytes]):
        if Path(os.fsdecode(path)) == broken:
            raise PermissionError("denied")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    listing = list_source_listing(tmp_path)

    assert [Path(file.path) for file in listing.files] == [good]
    assert len(listing.diagnostics) == 1
    assert listing.diagnostics[0].path == str(broken)
    assert "directory traversal failed" in listing.diagnostics[0].message


def test_default_file_walker_implements_the_core_seam(tmp_path: Path) -> None:
    file = tmp_path / "source.py"
    file.touch()
    walker = DefaultFileWalker()

    assert walker.list_source_listing(tmp_path) == [file]
    assert is_vcs_internal(tmp_path / ".git")
    assert not walker.is_vcs_internal(tmp_path / ".github")


def test_metadata_overflow_uses_unknown_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "huge.py"
    file.write_bytes(b"x")
    real_stat = Path.stat

    class HugeMetadata:
        st_mtime_ns = 1 << 80
        st_size = 1 << 80

    def stat(path: Path, *args: object, **kwargs: object):
        if path == file:
            return HugeMetadata()
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    item = list_source_listing(file).files[0]
    assert item.mtime == UNKNOWN_METADATA
    assert item.size == UNKNOWN_METADATA
    assert item.content_hash is not None


def test_prunes_root_repo_map_but_not_nested_one(tmp_path: Path) -> None:
    pack = tmp_path / "docs" / "repo-map" / "README.md"
    pack.parent.mkdir(parents=True)
    pack.touch()
    nested = tmp_path / "sub" / "docs" / "repo-map" / "keep.md"
    nested.parent.mkdir(parents=True)
    nested.touch()
    other = tmp_path / "docs" / "guide.md"
    other.touch()

    listing = list_source_listing(tmp_path)

    assert sorted(Path(file.path) for file in listing.files) == sorted([nested, other])


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
    )


def _git_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    return root


def _names(root: Path) -> list[str]:
    return [
        str(Path(f.path).relative_to(root)) for f in list_source_listing(root).files
    ]


def test_git_listing_omits_ignored_and_keeps_untracked_and_tracked(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("ignored/\n*.log\n", encoding="utf-8")
    (repo / "ignored").mkdir()
    (repo / "ignored" / "a.py").touch()
    (repo / "x.log").touch()
    (repo / "tracked.py").touch()
    _git(repo, "add", ".gitignore", "tracked.py")
    (repo / "untracked.py").touch()
    (repo / ".dotfile").touch()

    assert _names(repo) == [".dotfile", ".gitignore", "tracked.py", "untracked.py"]


def test_git_listing_skips_deleted_symlinks_gitlinks_and_nested_repos(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path / "repo")
    (repo / "gone.py").touch()
    (repo / "keep.py").touch()
    (repo / "link.py").symlink_to(repo / "keep.py")
    _git(repo, "add", "gone.py", "keep.py", "link.py")
    (repo / "gone.py").unlink()
    inner = _git_repo(tmp_path / "inner")
    (inner / "i.py").touch()
    _git(inner, "add", "i.py")
    _git(inner, "commit", "-qm", "i")
    _git(
        repo,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{_head(inner)},sub",
    )
    nested = _git_repo(repo / "nested")
    (nested / "n.py").touch()

    assert _names(repo) == ["keep.py"]


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_git_listing_prunes_every_path_component(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    for relative in (
        "pkg/node_modules/m.py",
        "pkg/__pycache__/c.py",
        "docs/repo-map/pack.md",
        ".varde/worktrees/t/w.py",
        ".varde/.scratch/s.py",
        "build/b.py",
        "pkg/build/ok.py",
    ):
        (repo / relative).parent.mkdir(parents=True, exist_ok=True)
        (repo / relative).touch()
    linked = repo / "wt"
    linked.mkdir()
    (linked / ".git").write_text("gitdir: ../.git/worktrees/wt\n")
    (linked / "w.py").touch()
    _git(repo, "add", "-A", "-f")

    assert _names(repo) == ["pkg/build/ok.py"]


def test_git_listing_from_subdirectory_uses_unresolved_sorted_paths(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path / "repo")
    sub = repo / "sub"
    sub.mkdir()
    (sub / "b.py").touch()
    (sub / "a.py").touch()
    (repo / "outside.py").touch()

    listing = list_source_listing(sub)

    assert [f.path for f in listing.files] == [str(sub / "a.py"), str(sub / "b.py")]


def test_empty_git_repo_lists_nothing(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")

    listing = list_source_listing(repo)

    assert listing.files == []
    assert listing.diagnostics == []


def test_falls_back_to_walk_when_git_listing_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (repo / "ignored.py").touch()
    monkeypatch.setattr(files, "run_git_bytes", lambda _args, _cwd: None)

    assert _names(repo) == [".gitignore", "ignored.py"]


def test_git_listing_keeps_non_utf8_filenames(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    name = os.fsdecode(b"bad\xff.py")
    try:
        (repo / name).touch()
    except OSError:
        pytest.skip("filesystem rejects non-UTF-8 names")

    assert _names(repo) == [name]


def test_git_listing_reports_unreadable_directory(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    locked = repo / "locked"
    locked.mkdir()
    (locked / "a.py").touch()
    (repo / "ok.py").touch()
    _git(repo, "add", "locked/a.py")
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK | os.X_OK):
            pytest.skip("permissions are not enforced")
        listing = list_source_listing(repo)
    finally:
        locked.chmod(0o700)

    assert [Path(f.path).name for f in listing.files] == ["ok.py"]
    assert [d.path for d in listing.diagnostics] == [str(locked / "a.py")]
