from __future__ import annotations

from varde_code.cli_packs import run
from varde_code.index.paths import repo_db_path

from .conftest import git


def test_build_refuses_in_linked_worktree(repo, tmp_path, capsys):
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-q", "-b", "side", str(linked))
    assert (linked / ".git").is_file()

    code = run(["map", "packs", "build", "--repo-root", str(linked)])

    assert code == 1
    assert "main checkout" in capsys.readouterr().err
    assert not repo_db_path(linked).parent.exists()
    assert not (linked / "docs" / "repo-map").exists()
    assert run(["map", "packs", "status", "--repo-root", str(linked)]) == 0
    assert run(["map", "packs", "build", "--repo-root", str(repo)]) == 0
