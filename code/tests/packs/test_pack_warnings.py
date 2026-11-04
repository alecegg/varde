from __future__ import annotations

import re

from varde_code.cli_packs import run
from varde_code.packs import DOC_DIR, README
from varde_code.packs.status import PackStatus
from varde_code.packs.warnings import collect_pack_warnings, pack_warnings

from .conftest import commit_all


def _status(path, behind, kind="module"):
    return PackStatus(path, kind, "abc", ".", behind > 0, behind)


def test_all_fresh_gives_no_warning():
    statuses = [_status(README, 0, "readme"), _status(f"{DOC_DIR}/modules/a.md", 0)]
    assert pack_warnings(statuses, True, [], 100) == []


def test_stale_module_pack_alone_gives_no_warning():
    statuses = [_status(README, 0, "readme"), _status(f"{DOC_DIR}/modules/a.md", 5)]
    assert pack_warnings(statuses, True, [], 100) == []


def test_readme_at_99_and_100_behind():
    assert pack_warnings([_status(README, 99, "readme")], True, [], 100) == []
    warnings = pack_warnings([_status(README, 100, "readme")], True, [], 100)
    assert len(warnings) == 1
    assert "100 commits behind" in warnings[0]


def test_missing_readme_and_listed_pack_warn():
    assert "README.md is missing" in pack_warnings([], False, [], 100)[0]
    warnings = pack_warnings([], True, [f"{DOC_DIR}/modules/a.md"], 100)
    assert warnings == [
        f"{DOC_DIR}/modules/a.md is missing; run: varde map packs build"
    ]


def test_collect_fresh_repo_has_no_warning(repo):
    run(["map", "packs", "build", "--repo-root", str(repo)])
    commit_all(repo, "packs")
    assert collect_pack_warnings(repo) == []


def test_collect_without_readme_warns(repo):
    assert any("README.md is missing" in w for w in collect_pack_warnings(repo))


def test_collect_missing_listed_pack_warns(repo):
    run(["map", "packs", "build", "--repo-root", str(repo)])
    (repo / DOC_DIR / "modules.txt").write_text("src\n")
    warnings = collect_pack_warnings(repo)
    assert any("modules/src.md is missing" in w for w in warnings)


def test_collect_git_error_returns_warning(repo):
    run(["map", "packs", "build", "--repo-root", str(repo)])
    readme = repo / README
    text = readme.read_text()
    patched = re.sub(r"commit: *[0-9a-f]{7,40}", "commit: " + "f" * 40, text, count=1)
    assert patched != text
    readme.write_text(patched)
    warnings = collect_pack_warnings(repo)
    assert len(warnings) == 1
    assert "packs status failed" in warnings[0]
