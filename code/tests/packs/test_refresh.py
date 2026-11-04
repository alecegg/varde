from __future__ import annotations

from varde_code.cli_packs import run

from .conftest import commit_all


def _build(repo, *flags):
    return run(["map", "packs", "build", *flags, "--repo-root", str(repo)])


def _list(repo, text="src/x\n"):
    (repo / "docs/repo-map").mkdir(parents=True, exist_ok=True)
    (repo / "docs/repo-map/modules.txt").write_text(text)
    commit_all(repo, "modules")


def test_all_then_stale_rewrites_nothing(repo, capsys):
    _list(repo)
    assert _build(repo, "--all") == 0
    commit_all(repo, "packs")
    pack = repo / "docs/repo-map/modules/src-x.md"
    assert pack.is_file() and (repo / "docs/repo-map/README.md").is_file()
    before = {p: p.read_bytes() for p in (repo / "docs/repo-map").rglob("*.md")}
    capsys.readouterr()

    assert _build(repo, "--stale") == 0

    assert "packs fresh" in capsys.readouterr().out
    assert before == {p: p.read_bytes() for p in before}


def test_stale_rebuilds_only_stale_module(repo, capsys):
    _list(repo, "src/x\nsrc\n")
    _build(repo, "--all")
    commit_all(repo, "packs")
    (repo / "src" / "y.py").write_text("x = 2\n")
    commit_all(repo, "edit")
    capsys.readouterr()

    assert _build(repo, "--stale") == 0

    out = capsys.readouterr().out
    assert "wrote docs/repo-map/modules/src.md" in out
    assert "src-x.md" not in out and "README" not in out


def test_stale_builds_missing_readme_and_packs(repo, capsys):
    _list(repo)
    assert _build(repo, "--stale") == 0
    out = capsys.readouterr().out
    assert "README.md" in out and "src-x.md" in out


def test_readme_rebuilt_at_threshold(repo, capsys):
    _list(repo)
    _build(repo, "--all")
    commit_all(repo, "packs")
    (repo / "src" / "y.py").write_text("x = 2\n")
    commit_all(repo, "edit")
    capsys.readouterr()
    assert _build(repo, "--stale", "--readme-max-behind", "1") == 0
    assert "README.md" in capsys.readouterr().out


def test_all_exits_two_on_missing_folder_and_writes_nothing(repo):
    _list(repo, "src/x\nnope\n")
    assert _build(repo, "--all") == 2
    assert not (repo / "docs/repo-map/README.md").exists()


def test_all_without_modules_file_and_bad_flag_combo(repo):
    assert _build(repo, "--all") == 2
    _list(repo)
    assert _build(repo, "--all", "--stale") == 2
    assert _build(repo, "--stale", "src/x") == 2
