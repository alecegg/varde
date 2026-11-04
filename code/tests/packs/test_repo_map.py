from __future__ import annotations

from varde_code.cli_packs import run
from varde_code.packs.header import parse_header
from varde_code.packs.repo_map import render_repo_map

from .conftest import git


def test_build_writes_readme_with_head_sha(repo, capsys):
    assert run(["map", "packs", "build", "--repo-root", str(repo)]) == 0

    readme = repo / "docs" / "repo-map" / "README.md"
    header = parse_header(readme.read_text())
    assert header is not None
    assert header.commit == git(repo, "rev-parse", "HEAD")
    assert (header.kind, header.scope, header.dirty) == ("repo-map", ".", False)
    assert "wrote docs/repo-map/README.md" in capsys.readouterr().out
    assert "## entrypoints" in readme.read_text()


def test_dirty_tree_is_noted_in_header(repo):
    (repo / "src" / "y.py").write_text("x = 1\n")

    run(["map", "packs", "build", "--repo-root", str(repo)])

    header = parse_header((repo / "docs/repo-map/README.md").read_text())
    assert header is not None and header.dirty


def test_non_git_repo_records_no_commit(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n")

    assert run(["map", "packs", "build", "--repo-root", str(root)]) == 0

    header = parse_header((root / "docs/repo-map/README.md").read_text())
    assert header is not None and header.commit == "none"


def test_render_is_header_then_sections():
    from varde_code.packs.header import Header

    header = Header("repo-map", "a" * 40, ".", "2026-10-30T00:00:00Z", "varde dev")
    text = render_repo_map({"entrypoints": []}, header)
    assert text.startswith("---\nkind: repo-map\ncommit: " + "a" * 40)
    assert "# Repo map" in text
