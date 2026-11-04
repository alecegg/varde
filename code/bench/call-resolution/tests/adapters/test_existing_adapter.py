"""Behavior tests for exporting existing resolver edges."""

import json
import os
import sqlite3
import subprocess

import pytest
from adapters.existing import export_edges
from adapters.existing.export import _grammar_cache_dir
from tree_sitter_language_pack import (
    PackConfig,
    configure,
    downloaded_languages,
)
from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.build import build


@pytest.fixture(autouse=True)
def required_grammars_are_cached():
    grammar_cache = _grammar_cache_dir(os.environ.copy())
    configure(PackConfig(cache_dir=grammar_cache))
    missing = {"python", "typescript"} - set(downloaded_languages())
    if missing:
        message = (
            "tree-sitter grammars are not prefetched in "
            f"{grammar_cache}: {', '.join(sorted(missing))}"
        )
        if os.environ.get("VARDE_BENCH_REQUIRE_GRAMMARS") == "1":
            pytest.fail(message)
        pytest.skip(message)


def test_exports_python_resolved_and_opaque_calls_with_function_ids(
    tmp_path, monkeypatch
):
    repo = tmp_path / "python-fixture"
    repo.mkdir()
    (repo / "helpers.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (repo / "main.py").write_text(
        "from helpers import helper\n\ndef run():\n    helper()\n    missing()\n",
        encoding="utf-8",
    )
    index_config = tmp_path / "expected-config"
    index_config.mkdir()
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(index_config))
    summary = build(repo, CodeExtractionProvider())
    with sqlite3.connect(summary.db_path) as connection:
        expected = dict(
            connection.execute(
                "SELECT name, CAST(id AS TEXT) FROM entities WHERE kind=0"
            )
        )

    rows = _load_edges(export_edges(repo))
    helper_edge = _edge_from(rows, expected["run"], 4)
    missing_edge = _edge_from(rows, expected["run"], 5)

    assert helper_edge == {
        "caller": expected["run"],
        "file": "main.py",
        "name": "helper",
        "site_line": 4,
        "callee": expected["helper"],
        "callee_file": "helpers.py",
        "callee_name": "helper",
        "callee_line": 1,
        "kind": "resolved",
        "pass": "local",
    }
    assert missing_edge["caller"] == expected["run"]
    assert missing_edge["callee"] is None
    assert missing_edge["kind"] == "opaque"
    assert "callee_file" not in missing_edge
    assert "callee_name" not in missing_edge


def test_exports_typescript_cross_file_call_with_function_ids(tmp_path, monkeypatch):
    repo = tmp_path / "typescript-fixture"
    repo.mkdir()
    (repo / "client.ts").write_text(
        "import { work } from './worker';\nexport function start() { work(); }\n",
        encoding="utf-8",
    )
    (repo / "worker.ts").write_text(
        "export function work() { return 1; }\n", encoding="utf-8"
    )
    _isolate_index_config(tmp_path, monkeypatch)
    expected = _function_ids(repo)

    rows = _load_edges(export_edges(repo))
    call = next(row for row in rows if row["caller"] == expected["start"])

    assert call == {
        "caller": expected["start"],
        "file": "client.ts",
        "name": "work",
        "site_line": 2,
        "callee": expected["work"],
        "callee_file": "worker.ts",
        "callee_name": "work",
        "callee_line": 1,
        "kind": "resolved",
        "pass": "local",
    }


def test_marks_ambiguous_caller_and_keeps_callee_resolution_separate(
    tmp_path, monkeypatch
):
    repo = tmp_path / "ambiguous-fixture"
    repo.mkdir()
    (repo / "ambiguous.py").write_text(
        "def repeated():\n    def repeated():\n        repeated()\n",
        encoding="utf-8",
    )
    _isolate_index_config(tmp_path, monkeypatch)

    rows = _load_edges(export_edges(repo))
    call = next(row for row in rows if row["site_line"] == 3)

    assert call["caller"] == "ambiguous"
    assert call["file"] == "ambiguous.py"
    assert call["name"] == "repeated"
    assert len(call["caller_candidates"]) == 2
    assert call["caller_candidates"] == sorted(call["caller_candidates"])
    assert call["kind"] == "opaque"
    assert call["callee"] is None


def test_assigns_module_level_call_a_file_specific_caller(tmp_path):
    repo = tmp_path / "module-fixture"
    repo.mkdir()
    (repo / "module.py").write_text("target()\n", encoding="utf-8")

    rows = _load_edges(export_edges(repo))

    assert len(rows) == 1
    assert rows[0]["caller"].startswith("module:")
    assert rows[0]["caller"].endswith("/module.py")
    assert rows[0]["site_line"] == 1
    assert rows[0]["file"] == "module.py"
    assert rows[0]["name"] == "target"
    assert rows[0]["callee"] is None
    assert rows[0]["kind"] == "opaque"


def test_isolated_build_failure_raises_with_the_inner_stderr_tail(
    tmp_path, monkeypatch
):
    from adapters.existing import export

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(
        export, "_grammar_cache_dir", lambda env: str(tmp_path / "grammars")
    )
    monkeypatch.setattr(
        export.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="HEAD" + "x" * 5000 + "TAIL"
        ),
    )

    with pytest.raises(RuntimeError) as raised:
        export.export_edges(repo)

    message = str(raised.value)
    tail = message.split("inner stderr tail:\n", 1)[1]
    assert len(tail) == 4096
    assert tail.endswith("TAIL")
    assert "HEAD" not in tail
    assert "exit 1" in message


def _isolate_index_config(tmp_path, monkeypatch):
    config = tmp_path / "expected-config"
    config.mkdir()
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))


def _function_ids(repo):
    summary = build(repo, CodeExtractionProvider())
    with sqlite3.connect(summary.db_path) as connection:
        return dict(
            connection.execute(
                "SELECT name, CAST(id AS TEXT) FROM entities WHERE kind=0"
            )
        )


def _load_edges(path):
    assert path.name.startswith("edges-")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    path.unlink()
    return rows


def _edge_from(rows, caller, line):
    return next(
        row for row in rows if row["caller"] == caller and row["site_line"] == line
    )
