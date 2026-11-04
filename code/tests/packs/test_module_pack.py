from __future__ import annotations

import json

from varde_code.cli_packs import run
from varde_code.index.paths import repo_db_path
from varde_code.packs.header import parse_header
from varde_code.packs.module_pack import slug

from .conftest import commit_all, git

PACK = "docs/repo-map/modules/src-x.md"


def _build(repo, folder="src/x"):
    return run(["map", "packs", "build", folder, "--repo-root", str(repo)])


def test_module_pack_has_sha_header_and_folder_scope(repo, capsys):
    assert _build(repo) == 0
    assert f"wrote {PACK}" in capsys.readouterr().out
    header = parse_header((repo / PACK).read_text())
    assert header is not None
    assert header.kind == "module-pack"
    assert header.scope == "src/x"
    assert len(header.commit) == 40


def test_pack_reuses_single_index(repo):
    _build(repo)
    db = repo_db_path(repo)
    inode = db.stat().st_ino
    _build(repo)
    assert db.stat().st_ino == inode


def test_missing_folder_exits_one(repo, capsys):
    assert _build(repo, "nope") == 1
    assert "folder_not_found" in capsys.readouterr().err
    assert not (repo / "docs/repo-map/modules").exists()


def test_path_outside_repo_is_rejected(repo):
    assert _build(repo, "..") == 1
    assert _build(repo, ".") == 1


def _module_status(repo, capsys):
    capsys.readouterr()
    run(["map", "packs", "status", "--json", "--repo-root", str(repo)])
    report = json.loads(capsys.readouterr().out)
    return next(pack for pack in report["packs"] if pack["scope"] == "src/x")


def test_outside_commit_leaves_module_pack_fresh(repo, capsys):
    _build(repo)
    commit_all(repo, "packs")
    (repo / "src" / "y.py").write_text("x = 2\n")
    commit_all(repo, "outside")
    status = _module_status(repo, capsys)
    assert (status["stale"], status["commits_behind"]) == (False, 0)


def test_inside_commit_makes_module_pack_stale(repo, capsys):
    _build(repo)
    commit_all(repo, "packs")
    (repo / "src" / "x" / "mod.py").write_text("x = 2\n")
    commit_all(repo, "inside")
    status = _module_status(repo, capsys)
    assert (status["stale"], status["commits_behind"]) == (True, 1)


def test_slug_is_collision_free():
    assert slug("a/b-c") != slug("a-b/c")
    assert slug("a-/b") != slug("a/-b")
    assert slug("a%2Db") != slug("a-b")


def test_pack_lists_only_folder_files(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path_factory.mktemp("cfg")))
    root = tmp_path_factory.mktemp("proj")
    (root / "a").mkdir()
    (root / "b").mkdir()
    (root / "a" / "one.py").write_text("def one():\n    return 1\n")
    (root / "a" / "two.py").write_text(
        "from a.one import one\n\n\ndef two():\n    return one()\n"
    )
    (root / "b" / "other.py").write_text("def other():\n    return 2\n")
    git(root, "init", "-q", "-b", "main")
    commit_all(root, "init")
    assert run(["map", "packs", "build", "a", "--repo-root", str(root)]) == 0
    text = (root / "docs/repo-map/modules/a.md").read_text()
    assert "- a/one.py" in text
    assert "other.py" not in text
