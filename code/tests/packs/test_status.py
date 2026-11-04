from __future__ import annotations

import json

from varde_code.cli_packs import run
from varde_code.packs.status import count_behind, touches_pack

from .conftest import commit_all


def _build_and_commit(repo):
    run(["map", "packs", "build", "--repo-root", str(repo)])
    commit_all(repo, "packs")


def test_committed_packs_are_fresh(repo):
    _build_and_commit(repo)
    assert run(["map", "packs", "status", "--check", "--repo-root", str(repo)]) == 0


def test_outside_change_makes_packs_stale(repo, capsys):
    _build_and_commit(repo)
    (repo / "src" / "y.py").write_text("x = 2\n")
    commit_all(repo, "edit")
    capsys.readouterr()

    code = run(
        [
            "map",
            "packs",
            "status",
            "--check",
            "--json",
            "--readme-max-behind",
            "1",
            "--repo-root",
            str(repo),
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 1
    assert report["packs"][0]["stale"] is True
    assert report["packs"][0]["commits_behind"] == 1
    assert report["index"]["present"] is True


def test_uncommitted_edit_is_not_stale(repo):
    _build_and_commit(repo)
    (repo / "src" / "y.py").write_text("x = 3\n")
    assert run(["map", "packs", "status", "--check", "--repo-root", str(repo)]) == 0


def test_missing_packs_fail_check_and_pass_without_check(repo, capsys):
    assert run(["map", "packs", "status", "--check", "--repo-root", str(repo)]) == 1
    assert "packs missing; run varde map packs build" in capsys.readouterr().err
    assert run(["map", "packs", "status", "--repo-root", str(repo)]) == 0


def test_git_error_exits_two(repo):
    _build_and_commit(repo)
    readme = repo / "docs/repo-map/README.md"
    text = readme.read_text().replace("commit: ", "commit: deadbeef", 1)
    readme.write_text(text)
    assert run(["map", "packs", "status", "--check", "--repo-root", str(repo)]) == 2


def test_usage_error_exits_two():
    assert run(["map", "packs", "status", "--bogus"]) == 2


def test_touches_pack_scope_rules():
    assert touches_pack(["a/b.py"], ".")
    assert not touches_pack(["docs/repo-map/README.md"], ".")
    assert touches_pack(["src/x/m.py"], "src/x")
    assert not touches_pack(["src/xy/m.py"], "src/x")
    assert count_behind([["src/y.py"], ["docs/repo-map/README.md"]], "src/x") == 0


def test_readme_threshold_and_orphan_packs(repo, capsys):
    _build_and_commit(repo)
    (repo / "src" / "y.py").write_text("x = 2\n")
    commit_all(repo, "edit")
    base = ["map", "packs", "status", "--check", "--repo-root", str(repo)]
    assert run(base) == 0
    assert run([*base, "--readme-max-behind", "1"]) == 1

    orphan = repo / "docs/repo-map/modules/gone.md"
    orphan.parent.mkdir(parents=True)
    orphan.write_text(
        (repo / "docs/repo-map/README.md")
        .read_text()
        .replace("scope: .", "scope: gone")
    )
    (repo / "docs/repo-map/modules.txt").write_text("src/x\n")
    commit_all(repo, "orphan")
    capsys.readouterr()
    assert run([*base, "--json", "--readme-max-behind", "5"]) == 0
    assert "gone.md" not in capsys.readouterr().out
