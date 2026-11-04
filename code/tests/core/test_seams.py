"""Contract tests for native code indexing and its public seams."""

from __future__ import annotations

import subprocess
from pathlib import Path

from varde_code.git import run_git
from varde_code.graph_model import Graph
from varde_code.index.build import build
from varde_code.index.slice import IndexService
from varde_code.model import ExtractOutput
from varde_code.seams import ExtractionProvider, FileWalker, GraphCache


def test_check_fresh_uses_tracked_files_for_committed_fixture_repo(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "tiny"
    repo_root.mkdir()
    (repo_root / "a.py").write_text("def first(): pass\n", encoding="utf-8")
    (repo_root / "b.py").write_text("def second(): pass\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo_root)], check=True)
    subprocess.run(["git", "-C", str(repo_root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )

    class Extractor:
        def extract(self, path: Path, source: str, language: str) -> ExtractOutput:
            from varde_code.extract.entity import extract_file

            return extract_file(str(path), source, language)

    build(repo_root, Extractor())
    service = IndexService()
    assert service.check_fresh(repo_root)
    (repo_root / "a.py").write_text("def changed(): return 1\n", encoding="utf-8")
    assert not service.check_fresh(repo_root)
    build(repo_root, Extractor())
    assert service.check_fresh(repo_root)


def test_graph_serialization_and_git_signature(tmp_path: Path) -> None:
    graph = Graph(paths={1: "src/a.py"}, out={1: [2]}, inc={2: [1]})
    assert Graph.from_dict(graph.to_dict()) == graph
    assert run_git(["rev-parse", "--show-toplevel"], tmp_path) is None
    assert all(
        protocol is not None
        for protocol in (FileWalker, IndexService, ExtractionProvider, GraphCache)
    )
