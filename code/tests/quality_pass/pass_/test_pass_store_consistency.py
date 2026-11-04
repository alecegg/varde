"""An interrupted pass leaves a consistent store and resumes from it."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from pass_support import (
    build_index,
    facts_by_path,
    measures_by_path,
    prepare_env,
    snapshot,
    write_repo,
)
from varde_code.quality_pass import resolve_hook
from varde_code.quality_pass.pass_ import extract as pass_extract
from varde_code.quality_pass.pass_ import read_facts, read_measures, run_quality_pass
from varde_code.quality_pass.store import open_store, quality_store_path

REPO = {
    "pkg/__init__.py": "",
    "pkg/helper.py": "def compute(value):\n    return value + 1\n",
    "pkg/main.py": (
        "import pkg.helper\n\n\ndef entry():\n    return pkg.helper.compute(2)\n"
    ),
    "pkg/standalone.py": "def lonely():\n    return 5\n",
}


def test_interrupted_pass_leaves_a_consistent_store_and_resumes(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, REPO)
    build_index(root)

    real = pass_extract.extract_record
    calls = {"count": 0}

    def flaky(indexed, raw):
        calls["count"] += 1
        if calls["count"] == 3:
            raise RuntimeError("simulated crash")
        return real(indexed, raw)

    monkeypatch.setattr(pass_extract, "extract_record", flaky)
    with pytest.raises(RuntimeError, match="simulated crash"):
        run_quality_pass(root, workers=1)

    interrupted = facts_by_path(root)
    assert sorted(interrupted) == ["pkg/__init__.py", "pkg/helper.py"]
    assert all(record["contract"] == "facts-2" for record in interrupted.values())
    assert measures_by_path(root) == {}

    monkeypatch.setattr(pass_extract, "extract_record", real)
    resumed = run_quality_pass(root, workers=1)

    assert resumed.facts_reused == 2
    assert resumed.facts_recomputed == ("pkg/main.py", "pkg/standalone.py")
    complete = snapshot(root)

    uncached = run_quality_pass(root, workers=1, no_cache=True)
    assert uncached.facts_recomputed == tuple(sorted(REPO))
    assert snapshot(root) == complete


def test_interrupted_pass_after_the_edges_write_resumes(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, REPO)
    build_index(root)

    real = resolve_hook.edges_for_file
    calls = {"count": 0}

    def flaky(context, path):
        calls["count"] += 1
        if calls["count"] == 3:
            raise RuntimeError("simulated edge crash")
        return real(context, path)

    monkeypatch.setattr(resolve_hook, "edges_for_file", flaky)
    with pytest.raises(RuntimeError, match="simulated edge crash"):
        run_quality_pass(root, workers=1)

    assert len(facts_by_path(root)) == len(REPO)
    assert measures_by_path(root) == {}

    monkeypatch.setattr(resolve_hook, "edges_for_file", real)
    resumed = run_quality_pass(root, workers=1)
    assert resumed.facts_reused == len(REPO)
    assert resumed.edges_reused == 2
    assert resumed.edges_recomputed == ("pkg/main.py", "pkg/standalone.py")
    complete = snapshot(root)

    run_quality_pass(root, workers=1, no_cache=True)
    assert snapshot(root) == complete


def test_two_concurrent_passes_on_one_store_both_succeed(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, REPO)
    build_index(root)

    def one_pass(_index):
        return run_quality_pass(root, workers=1, no_cache=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        summaries = list(pool.map(one_pass, range(2)))

    assert len(summaries) == 2
    assert all(summary.facts_reused == 0 for summary in summaries)
    final = snapshot(root)
    run_quality_pass(root, workers=1, no_cache=True)
    assert snapshot(root) == final


def test_garbage_collection_counts_deleted_rows_under_no_cache(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, {"src/app.py": "def run():\n    return 1\n"})
    build_index(root)
    run_quality_pass(root, workers=1)
    with open_store(quality_store_path(root).parent) as store:
        store.put_facts(
            "gone.py", "stale-key", {"contract": "facts-2", "path": "gone.py"}
        )

    summary = run_quality_pass(root, workers=1, no_cache=True)

    assert summary.garbage_collected == 1
    assert [record["path"] for record in read_facts(root)] == ["src/app.py"]


def test_read_facts_normalizes_a_facts_1_record(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    root = tmp_path / "repo"
    root.mkdir()
    legacy = {
        "contract": "facts-1",
        "path": "a.py",
        "language": "python",
        "content_hash": "blake2b-legacy",
        "tokens": 12,
        "excluded": None,
        "import_fan_out": None,
        "functions": [
            {
                "id": "a.py::f#1",
                "name": "f",
                "owner": None,
                "line": 1,
                "end_line": 2,
                "tokens": 12,
                "params": 0,
                "cognitive": 1,
                "exempt_role": None,
                "file_private": False,
                "callers_in_module": None,
                "fragment_scope": None,
                "module": None,
                "depth": None,
                "fan_out": None,
                "tree_size": None,
                "cross_module_depth": None,
                "opaque_calls": None,
                "depth_capped": None,
                "name_issues": [],
            }
        ],
        "data_functions": [],
        "call_sites": [],
        "call_coverage": None,
        "unresolved_share": None,
        "structure_confidence": None,
        "diagnostics": [],
    }
    store_dir = quality_store_path(root).parent
    store_dir.mkdir(parents=True, exist_ok=True)
    with open_store(store_dir) as store:
        store.put_facts("a.py", "legacy-key", legacy)

    records = list(read_facts(root))

    assert len(records) == 1
    record = records[0]
    assert record["contract"] == "facts-2"
    assert record["markers"] == []
    assert record["comment_parity"] == {"tokens": 12, "comment_tokens": 0}
    assert record["unmeasured_regions"] == []
    assert record["functions"][0]["overload_pair"] is None
    assert record["functions"][0]["id"] == "a.py::f#1"


def test_readers_are_empty_without_a_store(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    root = tmp_path / "repo"
    root.mkdir()

    assert list(read_facts(root)) == []
    assert list(read_measures(root)) == []
