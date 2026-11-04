"""Contract tests for the optional plugin hooks in the facts core."""

from types import SimpleNamespace

import varde_code.quality_pass.facts as facts_module
from varde_code.quality_pass.facts import extract_facts

SOURCE = "def alpha():\n    return 1\n\ndef beta():\n    return 2\n"
OVERLOAD_SOURCE = "def beta():\n    return 1\n\ndef beta(value):\n    return value\n"
SHORT_SOURCE = "def cfg():\n    return 1\n"


def _extract_with(monkeypatch, plugin, source=SOURCE, path="hooks.py"):
    monkeypatch.setattr(facts_module, "language_module", lambda language: plugin)
    return extract_facts(source, "python", path)


def test_without_plugin_there_are_no_regions_or_pairs():
    record = extract_facts(OVERLOAD_SOURCE, "python", "hooks.py")

    assert record["contract"] == "facts-2"
    assert record["unmeasured_regions"] == []
    assert [row["overload_pair"] for row in record["functions"]] == [None, None]


def test_unmeasured_regions_are_sorted_and_deduplicated(monkeypatch):
    plugin = SimpleNamespace(
        unmeasured_regions=lambda root, source: [
            {"kind": "macro", "start_line": 3, "end_line": 3},
            {"kind": "template", "start_line": 1, "end_line": 2},
            {"kind": "macro", "start_line": 3, "end_line": 3},
        ]
    )

    record = _extract_with(monkeypatch, plugin)

    assert record["unmeasured_regions"] == [
        {"kind": "template", "start_line": 1, "end_line": 2},
        {"kind": "macro", "start_line": 3, "end_line": 3},
    ]


def test_filter_name_issues_sees_core_and_convention_issues(monkeypatch):
    plugin = SimpleNamespace(
        convention_issues=lambda record: ["convention"],
        filter_name_issues=lambda record, issues: [
            issue for issue in issues if issue != "abbreviation"
        ],
    )

    record = _extract_with(monkeypatch, plugin, SHORT_SOURCE)

    assert record["functions"][0]["name_issues"] == ["convention"]


def test_overload_pairs_marks_both_records_with_path_scoped_ids(monkeypatch):
    plugin = SimpleNamespace(
        overload_pairs=lambda records, root, source: [("beta#1", "beta#2")]
    )

    record = _extract_with(monkeypatch, plugin, OVERLOAD_SOURCE)

    assert [row["overload_pair"] for row in record["functions"]] == [
        "hooks.py::beta#2",
        "hooks.py::beta#1",
    ]


def test_overload_pairs_ignore_unknown_ids(monkeypatch):
    plugin = SimpleNamespace(
        overload_pairs=lambda records, root, source: [("beta#1", "missing#1")]
    )

    record = _extract_with(monkeypatch, plugin, OVERLOAD_SOURCE)

    assert [row["overload_pair"] for row in record["functions"]] == [None, None]


def test_plugin_verified_role_may_return_test(monkeypatch):
    plugin = SimpleNamespace(
        verified_role=lambda record, node, body, source: "test",
    )

    record = _extract_with(monkeypatch, plugin)

    assert [row["exempt_role"] for row in record["functions"]] == ["test", "test"]
