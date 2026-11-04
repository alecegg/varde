from __future__ import annotations

from varde_code.cli_packs import run
from varde_code.packs.filter import drop_excluded, read_excluded

from .conftest import commit_all

ROOT = "/r"
DATA = {
    "entrypoints": [{"file": "/r/bench/a.py"}, {"file": "/r/src/b.py"}],
    "foundational_files": [{"file": "/r/bench/x/c.py"}, {"file": "/r/benchmark/d.py"}],
    "symbols": [{"file": "/r/bench/a.py", "symbol": "f"}],
    "hotspots": [],
    "flows": [{"root": {"file": "/r/bench/a.py"}}, {"root": {"file": "/r/src/b.py"}}],
    "subsystems": [
        {"name": "n", "members": ["/r/bench/a.py", "/r/src/b.py"]},
        {"name": "gone", "members": ["/r/bench/a.py"]},
    ],
    "module_layers": {
        "edges": [
            {"from_module": "bench", "to_module": "src", "crossing_files": 1},
            {"from_module": "src", "to_module": "core", "crossing_files": 2},
        ],
        "cycles": [["bench", "src"], ["src", "core"]],
    },
}


def test_drop_excluded_removes_folder_paths_only():
    result = drop_excluded(DATA, ["bench"], ROOT)
    assert result["entrypoints"] == [{"file": "/r/src/b.py"}]
    assert result["foundational_files"] == [{"file": "/r/benchmark/d.py"}]
    assert result["symbols"] == []
    assert result["flows"] == [{"root": {"file": "/r/src/b.py"}}]
    assert result["subsystems"] == [{"name": "n", "members": ["/r/src/b.py"]}]
    assert [e["to_module"] for e in result["module_layers"]["edges"]] == ["core"]
    assert result["module_layers"]["cycles"] == [["src", "core"]]


def test_module_layers_with_absolute_module_paths_are_filtered():
    layers = {
        "edges": [
            {"from_module": "/r/bench/q/x", "to_module": "/r/src", "crossing_files": 1},
            {"from_module": "/r/src", "to_module": "/r/core", "crossing_files": 2},
        ],
        "cycles": [["/r/bench/q", "/r/src"], ["/r/src", "/r/core"]],
    }
    result = drop_excluded({"module_layers": layers}, ["bench"], ROOT)
    assert [e["to_module"] for e in result["module_layers"]["edges"]] == ["/r/core"]
    assert result["module_layers"]["cycles"] == [["/r/src", "/r/core"]]


def test_no_folders_returns_data_unchanged():
    assert drop_excluded(DATA, [], ROOT) is DATA


def test_read_excluded_skips_comments_and_blanks(tmp_path):
    (tmp_path / "docs/repo-map").mkdir(parents=True)
    (tmp_path / "docs/repo-map/exclude.txt").write_text("# c\nbench/\n\nold # x\n")
    assert read_excluded(tmp_path) == ["bench", "old"]
    assert read_excluded(tmp_path / "none") == []


def test_built_pack_omits_excluded_folder_and_empty_layer_line(repo):
    (repo / "bench").mkdir()
    (repo / "bench" / "b.py").write_text("def bench_only():\n    return 1\n")
    (repo / "docs/repo-map").mkdir(parents=True)
    (repo / "docs/repo-map/exclude.txt").write_text("bench\n")
    commit_all(repo, "bench")
    assert run(["map", "packs", "build", "--repo-root", str(repo)]) == 0
    text = (repo / "docs/repo-map/README.md").read_text()
    assert "bench/b.py" not in text
    assert "-  →  (0 files)" not in text
