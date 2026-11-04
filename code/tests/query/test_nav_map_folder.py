from __future__ import annotations

import subprocess

import pytest
from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.build import build
from varde_code.query.nav_map import format_map, in_folder, nav_map


@pytest.fixture
def indexed(tmp_path_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    root = tmp_path_factory.mktemp("proj")
    (root / "big").mkdir(parents=True)
    (root / "small").mkdir()
    for number in range(120):
        (root / "big" / f"m{number}.py").write_text(
            f"def f{number}():\n    return {number}\n"
        )
    (root / "big" / "use.py").write_text(
        "".join(f"from big.m{n} import f{n}\n" for n in range(120))
        + "".join(f"f{n}()\n" for n in range(120))
    )
    (root / "small" / "tiny.py").write_text("def tiny():\n    return 1\n")
    (root / "small" / "caller.py").write_text(
        "from small.tiny import tiny\n\n\ndef go():\n    return tiny()\n"
    )
    for args in (
        ["init", "-q", "-b", "main"],
        ["add", "-A"],
        ["commit", "-q", "-m", "i"],
    ):
        subprocess.run(  # noqa: S603 - Runs git with controlled arguments in a temporary repo.
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
            cwd=root,
            check=True,
            capture_output=True,
        )
    summary = build(root, CodeExtractionProvider())
    return {"repoRoot": str(root), "dbPath": summary.db_path}


def test_unset_folder_matches_default(indexed):
    assert nav_map({**indexed, "folder": None}) == nav_map(indexed)


def test_small_folder_is_not_crowded_out_by_repo_wide_caps(indexed):
    repo_wide = nav_map(indexed)
    scoped = nav_map({**indexed, "folder": "small"})
    assert not any("/small/" in item["file"] for item in repo_wide["hotspots"])
    assert {item["file"].rsplit("/", 2)[-2:][1] for item in scoped["hotspots"]} == {
        "tiny.py",
        "caller.py",
    }
    assert all(
        "/small/" in item["file"]
        for name in ("foundational_files", "symbols", "entrypoints")
        for item in scoped[name]
    )
    assert any(
        i["file"].endswith("/small/tiny.py") for i in scoped["foundational_files"]
    )
    assert "/small/tiny.py" in format_map(scoped)


def test_in_folder_matches_whole_segments():
    assert in_folder("a/b.py", "a") and in_folder("a", "a")
    assert not in_folder("ab/b.py", "a")
    assert in_folder("anything", None)


def test_unset_folder_format_map_keeps_absolute_paths(indexed):
    # Relative rendering is a packs concern; plain `varde map` stays unchanged.
    assert indexed["repoRoot"] in format_map(nav_map(indexed))
