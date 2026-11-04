"""Cold/warm/no-cache equivalence and one-file-edit invalidation for the pass."""

from __future__ import annotations

import os

import pytest
from pass_support import (
    build_index,
    facts_by_path,
    measures_by_path,
    prepare_env,
    refresh_index,
    snapshot,
    write_repo,
)
from varde_code.quality_pass import resolve_hook
from varde_code.quality_pass.pass_ import run_quality_pass

REPO = {
    "pkg/__init__.py": "",
    "pkg/helper.py": "def compute(value):\n    return value + 1\n",
    "pkg/main.py": (
        "import pkg.helper\n\n\ndef entry():\n    return pkg.helper.compute(2)\n"
    ),
    "solo/standalone.py": "def lonely():\n    return 5\n",
}


def _cold(root):
    summary = run_quality_pass(root, workers=1)
    assert summary.facts_reused == 0
    assert summary.facts_recomputed == tuple(sorted(REPO))
    assert summary.edges_recomputed == tuple(sorted(REPO))
    assert summary.measures_recomputed == tuple(sorted(REPO))
    assert summary.file_count == len(REPO)
    return summary


def test_cold_warm_and_no_cache_produce_identical_facts_and_measures(
    tmp_path, monkeypatch
):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, REPO)
    build_index(root)

    cold = _cold(root)
    assert cold.path_classes_written == tuple(sorted(REPO))
    cold_snapshot = snapshot(root)

    warm = run_quality_pass(root, workers=1)
    assert warm.facts_recomputed == ()
    assert warm.edges_recomputed == ()
    assert warm.measures_recomputed == ()
    assert warm.path_classes_written == ()
    assert warm.facts_reused == len(REPO)
    assert warm.edges_reused == len(REPO)
    assert warm.measures_reused == len(REPO)
    assert snapshot(root) == cold_snapshot

    uncached = run_quality_pass(root, workers=1, no_cache=True)
    assert uncached.facts_reused == 0
    assert uncached.facts_recomputed == tuple(sorted(REPO))
    assert snapshot(root) == cold_snapshot


def test_facts_records_are_facts_2_with_the_optional_fields(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, REPO)
    build_index(root)
    run_quality_pass(root, workers=1)

    record = facts_by_path(root)["pkg/helper.py"]
    assert record["contract"] == "facts-2"
    assert record["path"] == "pkg/helper.py"
    assert record["language"] == "python"
    assert record["markers"] == []
    assert record["unmeasured_regions"] == []
    assert record["comment_parity"] == {
        "tokens": record["tokens"],
        "comment_tokens": 0,
    }
    assert record["imports"] == []
    assert len(record["functions"]) == 1
    function = record["functions"][0]
    assert function["id"] == "pkg/helper.py::compute#1"
    assert function["name"] == "compute"
    assert function["tokens"] > 0
    assert function["overload_pair"] is None


def test_editing_one_file_recomputes_only_its_merkle_closure(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, REPO)
    build_index(root)
    run_quality_pass(root, workers=1)
    before = measures_by_path(root)

    # L3 measures are module-scoped, so an edit recomputes the changed file's
    # module and leaves other modules bit-identical.
    (root / "solo/standalone.py").write_text(
        "def lonely():\n    return extra()\n\n\ndef extra():\n    return 6\n",
        encoding="utf-8",
    )
    refresh_index(root)
    leaf = run_quality_pass(root, workers=1)

    assert leaf.facts_recomputed == ("solo/standalone.py",)
    assert leaf.edges_recomputed == ("solo/standalone.py",)
    assert leaf.measures_recomputed == ("solo/standalone.py",)
    after_leaf = measures_by_path(root)
    assert after_leaf["solo/standalone.py"] != before["solo/standalone.py"]
    for untouched in ("pkg/__init__.py", "pkg/helper.py", "pkg/main.py"):
        assert after_leaf[untouched] == before[untouched]

    (root / "pkg/helper.py").write_text(
        "def compute2(value):\n    return value + 2\n", encoding="utf-8"
    )
    refresh_index(root)
    callee = run_quality_pass(root, workers=1)

    assert callee.facts_recomputed == ("pkg/helper.py",)
    assert callee.edges_recomputed == ("pkg/helper.py", "pkg/main.py")
    assert set(callee.measures_recomputed) == {
        "pkg/__init__.py",
        "pkg/helper.py",
        "pkg/main.py",
    }
    assert "solo/standalone.py" not in callee.measures_recomputed
    after_callee = measures_by_path(root)
    assert after_callee["pkg/main.py"] != after_leaf["pkg/main.py"]
    assert after_callee["solo/standalone.py"] == after_leaf["solo/standalone.py"]


def test_touching_a_file_without_changing_content_recomputes_nothing(
    tmp_path, monkeypatch
):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, REPO)
    build_index(root)
    run_quality_pass(root, workers=1)

    target = root / "solo/standalone.py"
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    refresh_index(root)
    summary = run_quality_pass(root, workers=1)

    assert summary.facts_recomputed == ()
    assert summary.edges_recomputed == ()
    assert summary.measures_recomputed == ()
    assert summary.facts_reused == len(REPO)


def test_import_edge_makes_a_callee_deep_enough_to_be_measured(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(
        root,
        {
            "pkg/__init__.py": "",
            "pkg/helper.py": "def compute(value):\n    return value + 1\n",
            "pkg/main.py": (
                "import pkg.helper\n\n\ndef entry():\n"
                "    return pkg.helper.compute(2)\n"
            ),
        },
    )
    build_index(root)
    run_quality_pass(root, workers=1)

    measures = measures_by_path(root)
    entry = measures["pkg/main.py"]["functions"]["pkg/main.py::entry#1"]
    assert entry["depth"] == 1
    assert entry["distinct_callees"] == 1
    assert entry["fan_out"] == 1
    assert entry["tree_size"] == 1
    assert entry["opaque_calls"] == 0
    assert measures["pkg/main.py"]["import_fan_out"] == 1
    compute = measures["pkg/helper.py"]["functions"]["pkg/helper.py::compute#1"]
    assert compute["callers_in_module"] == 1
    assert compute["fragment_scope"] == "module"


@pytest.mark.parametrize("workers", [1, 2])
def test_worker_count_does_not_change_stored_results(tmp_path, monkeypatch, workers):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, REPO)
    build_index(root)

    run_quality_pass(root, workers=workers)
    cold = snapshot(root)
    run_quality_pass(root, workers=1, no_cache=True)

    assert snapshot(root) == cold


def _degradation_repo(root):
    write_repo(
        root,
        {
            "src/entry.py": (
                "from helper import known\n\ndef entry():\n    return known()\n"
            ),
            "src/helper.py": "def known():\n    return 1\n",
        },
    )
    build_index(root)


def test_resolver_error_degrades_one_file_and_is_stable_without_caching(
    tmp_path, monkeypatch
):
    root = prepare_env(monkeypatch, tmp_path)
    _degradation_repo(root)
    original = resolve_hook.quality_resolve.edges_for_file

    def fail_one(context, path):
        if path == "src/entry.py":
            raise LookupError("test resolver failure")
        return original(context, path)

    monkeypatch.setattr(resolve_hook.quality_resolve, "edges_for_file", fail_one)
    cold = run_quality_pass(root, workers=1)
    cold_snapshot = snapshot(root)
    warm = run_quality_pass(root, workers=1)

    assert cold.diagnostics == ("resolver_error: LookupError: src/entry.py",)
    assert warm.diagnostics == cold.diagnostics
    assert warm.edges_recomputed == ("src/entry.py",)
    assert facts_by_path(root)["src/entry.py"]["diagnostics"][-1] == cold.diagnostics[0]
    assert snapshot(root) == cold_snapshot
    entry = measures_by_path(root)["src/entry.py"]["functions"]["src/entry.py::entry#1"]
    helper = measures_by_path(root)["src/helper.py"]["functions"][
        "src/helper.py::known#1"
    ]
    assert entry["fan_out"] == 1
    assert entry["opaque_calls"] == 1
    assert helper["callers_in_module"] == 0
    assert all("src/helper.py" not in diagnostic for diagnostic in warm.diagnostics)


def test_resolver_digest_error_degrades_file_without_raising(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    _degradation_repo(root)
    original = resolve_hook.quality_resolve.digest_for_file

    def fail_one(context, path):
        if path == "src/entry.py":
            raise OSError("test digest failure")
        return original(context, path)

    monkeypatch.setattr(resolve_hook.quality_resolve, "digest_for_file", fail_one)
    cold = run_quality_pass(root, workers=1)
    cold_snapshot = snapshot(root)
    warm = run_quality_pass(root, workers=1)

    assert cold.diagnostics == ("resolver_error: OSError: src/entry.py",)
    assert warm.diagnostics == cold.diagnostics
    assert warm.edges_recomputed == ("src/entry.py",)
    assert snapshot(root) == cold_snapshot
    entry = measures_by_path(root)["src/entry.py"]["functions"]["src/entry.py::entry#1"]
    assert entry["fan_out"] == 1
    assert entry["opaque_calls"] == 1


def test_prepare_error_degrades_all_files_and_recomputes_after_recovery(
    tmp_path, monkeypatch
):
    root = prepare_env(monkeypatch, tmp_path)
    _degradation_repo(root)
    original = resolve_hook.quality_resolve.prepare

    def fail_prepare(*args, **kwargs):
        raise RuntimeError("test prepare failure")

    with monkeypatch.context() as patch:
        patch.setattr(resolve_hook.quality_resolve, "prepare", fail_prepare)
        failed = run_quality_pass(root, workers=1)
        assert failed.diagnostics == (
            "resolver_error: RuntimeError: src/entry.py",
            "resolver_error: RuntimeError: src/helper.py",
        )
        assert (
            measures_by_path(root)["src/entry.py"]["functions"][
                "src/entry.py::entry#1"
            ]["opaque_calls"]
            == 1
        )

    assert resolve_hook.quality_resolve.prepare is original
    recovered = run_quality_pass(root, workers=1)
    assert recovered.diagnostics == ()
    assert recovered.edges_recomputed == ("src/entry.py", "src/helper.py")
    assert not any(
        item.startswith("resolver_error: ")
        for record in facts_by_path(root).values()
        for item in record["diagnostics"]
    )
    assert (
        measures_by_path(root)["src/entry.py"]["functions"]["src/entry.py::entry#1"][
            "opaque_calls"
        ]
        == 0
    )
