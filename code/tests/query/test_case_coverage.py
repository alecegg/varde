from __future__ import annotations

from pathlib import Path

from varde_code.index.build import build
from varde_code.index.paths import repo_db_path
from varde_code.index.prune import run_in
from varde_code.model import ExtractOutput
from varde_code.query import dispatch


class Extractor:
    def extract(self, path: Path, source: str, language: str) -> ExtractOutput:
        from varde_code.extract.entity import extract_file

        return extract_file(str(path), source, language)


def test_built_three_file_index_supports_path_symbol_and_neighbor_queries(
    tmp_path, monkeypatch
):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("from b import helper\ndef f(): return helper()\n")
    (root / "b.py").write_text("def helper(): return 7\n")
    (root / "c.py").write_text("def other(): return 0\n")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    summary = build(root, Extractor())
    params = {"repoRoot": str(root), "dbPath": summary.db_path}

    path_result = dispatch(
        "map_path",
        {**params, "sourceFile": str(root / "a.py"), "targetFile": str(root / "b.py")},
    )
    symbols = dispatch("symbols_in_file", {**params, "filePath": str(root / "a.py")})
    neighbors = dispatch("dependencies", {**params, "filePath": "a.py"})

    assert path_result["ok"] is True
    assert [Path(item).name for item in path_result["data"]] == ["a.py", "b.py"]
    assert [item["name"] for item in symbols["data"]] == ["f"]
    assert any("b.py" in str(item) for item in neighbors["data"])
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    missing = dispatch(
        "symbols_in_file",
        {
            "repoRoot": str(empty_root),
            "dbPath": str(repo_db_path(empty_root)),
            "filePath": "a.py",
        },
    )
    assert missing["ok"] is False
    assert missing["data"]["error"]["code"] == "index_missing"

    config = tmp_path / "config"
    missing = tmp_path / "gone"
    stale_path = config / "code" / "repos-py" / "orphan"
    stale_path.mkdir(parents=True)
    (stale_path / "source-root").write_text(str(missing))
    pruned = run_in(config, {"apply": False})
    assert pruned["counts"]["wouldRemove"] == 1
