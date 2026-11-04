"""Pass-level exclusion ledger, unmeasured regions and D15 confidence."""

from __future__ import annotations

from pass_support import (
    build_index,
    facts_by_path,
    measures_by_path,
    prepare_env,
    write_repo,
)
from varde_code.quality_pass.pass_ import run_quality_pass

TEMPLATE_CPP = (
    "template <typename T>\n"
    "T maxv(T a, T b) {\n"
    "    return a > b ? a : b;\n"
    "}\n"
    "\n"
    "int plain() {\n"
    "    return 1;\n"
    "}\n"
)


def test_summary_reports_the_exclusion_ledger(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(
        root,
        {
            "src/app.py": "def run():\n    return 1\n",
            "vendor/lib.py": "def lib():\n    return 2\n",
            "generated/out.py": "def gen():\n    return 3\n",
        },
    )
    build_index(root)

    summary = run_quality_pass(root, workers=1)

    assert ("generated/out.py", "generated directory convention") in summary.exclusions
    assert ("vendor/lib.py", "vendored directory convention") in summary.exclusions
    assert all(path != "src/app.py" for path, _reason in summary.exclusions)
    assert summary.exclusions == tuple(sorted(summary.exclusions))


def test_functions_intersecting_an_unmeasured_region_have_null_graph_measures(
    tmp_path, monkeypatch
):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, {"src/t.cpp": TEMPLATE_CPP})
    build_index(root)

    run_quality_pass(root, workers=1)

    assert facts_by_path(root)["src/t.cpp"]["unmeasured_regions"] == [
        {"kind": "template", "start_line": 1, "end_line": 4}
    ]
    functions = measures_by_path(root)["src/t.cpp"]["functions"]
    unmeasured = functions["src/t.cpp::maxv#1"]
    assert unmeasured["depth"] is None
    assert unmeasured["fan_out"] is None
    assert unmeasured["tree_size"] is None
    assert unmeasured["cross_module_depth"] is None
    measured = functions["src/t.cpp::plain#1"]
    assert measured["depth"] == 0
    assert measured["fan_out"] == 0
    assert measured["tree_size"] == 0


def test_high_unresolved_share_lowers_structure_confidence(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(
        root,
        {
            "pkg/__init__.py": "",
            "pkg/a.py": "def f():\n    return foo() + bar()\n",
            "pkg/z.py": "def foo():\n    return 1\n\n\ndef bar():\n    return 2\n",
        },
    )
    build_index(root)

    run_quality_pass(root, workers=1)

    record = measures_by_path(root)["pkg/a.py"]
    assert record["call_coverage"] == {
        "resolved": 0,
        "ambiguous": 0,
        "opaque": 2,
        "external": 0,
    }
    assert record["unresolved_share"] == 1_000_000
    assert record["structure_confidence"] == "low"
    assert record["import_fan_out"] is None
