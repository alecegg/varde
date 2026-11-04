from __future__ import annotations

import os

from varde_code.cli_packs import run
from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.incremental import refresh
from varde_code.index.paths import repo_db_path


def _state(repo):
    db = repo_db_path(repo)
    stat = db.stat()
    return db, stat.st_ino


def test_repeat_builds_reuse_single_index(repo):
    args = ["map", "packs", "build", "--repo-root", str(repo)]
    assert run(args) == 0
    first = _state(repo)
    folders = sorted(os.listdir(first[0].parent.parent))

    assert run(args) == 0
    assert run(args) == 0

    assert _state(repo) == first
    assert sorted(os.listdir(first[0].parent.parent)) == folders
    assert len(folders) == 1


def test_changed_file_updates_same_index_in_place(repo):
    args = ["map", "packs", "build", "--repo-root", str(repo)]
    run(args)
    db, inode = _state(repo)
    (repo / "src" / "y.py").write_text("x = 9\n")

    assert run(args) == 0

    assert _state(repo) == (db, inode)


def test_no_change_refresh_in_git_repo_leaves_index_mtime_unchanged(repo):
    # `map packs build` rewrites docs/repo-map/README.md (new generated_at),
    # which the index also walks, so settle that file before measuring.
    run(["map", "packs", "build", "--repo-root", str(repo)])
    extractor = CodeExtractionProvider()
    refresh(repo, extractor)
    db = repo_db_path(repo)
    before = db.stat().st_mtime_ns

    summary = refresh(repo, extractor)

    assert summary.reparsed == 0
    assert db.stat().st_mtime_ns == before


def test_second_build_rewrites_no_pack_and_leaves_index_unchanged(repo):
    readme = ["map", "packs", "build", "--repo-root", str(repo)]
    module = [*readme, "src"]
    run(readme)
    run(module)
    packs = [repo / "docs/repo-map/README.md", repo / "docs/repo-map/modules/src.md"]
    before = [path.stat().st_mtime_ns for path in [*packs, repo_db_path(repo)]]

    assert run(readme) == 0
    assert run(module) == 0

    after = [path.stat().st_mtime_ns for path in [*packs, repo_db_path(repo)]]
    assert after == before
    for path in packs:
        assert str(repo) not in path.read_text()
        assert str(repo.resolve()) not in path.read_text()
