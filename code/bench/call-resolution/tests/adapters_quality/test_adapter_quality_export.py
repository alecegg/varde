from __future__ import annotations

import json
from pathlib import Path

import pytest
from adapters import quality


def _fixture_repo(root: Path) -> Path:
    (root / "a.py").write_text(
        "def duplicate(): return 1\n"
        "def duplicate(): return 2\n"
        "def unique(): return 4\n"
        "def caller():\n"
        "    duplicate()\n"
        "    unique()\n"
        "    missing_api()\n"
        "    self.missing()\n",
        encoding="utf-8",
    )
    (root / "b.py").write_text(
        "class Box:\n    def __init__(self): pass\ndef helper(): return 1\n",
        encoding="utf-8",
    )
    (root / "c.py").write_text("def spare(): return 3\n", encoding="utf-8")
    return root


def _edges(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_exports_contract_edges_and_function_ids(tmp_path: Path) -> None:
    exported = quality.export_edges(_fixture_repo(tmp_path))
    rows = _edges(exported)
    assert {row["file"] for row in rows} == {"a.py"}
    assert all(row["caller"] == "a.py::caller#1" for row in rows)
    assert {row["kind"] for row in rows} >= {
        "ambiguous",
        "resolved",
        "external",
        "opaque",
    }
    resolved = next(row for row in rows if row["name"] == "unique")
    assert resolved["callee"] == "a.py::unique#1"
    assert resolved["callee_file"] == "a.py"
    assert resolved["callee_name"] == "unique"
    assert isinstance(resolved["callee_line"], int)
    assert all(
        row["pass"] in {"local", "imported", "receiver", "namespace", "type"}
        for row in rows
    )


def test_file_failure_warns_and_continues(tmp_path: Path, monkeypatch) -> None:
    _fixture_repo(tmp_path)
    original = quality.extract_facts

    def fail_one(source, language, path=""):
        if path == "b.py":
            raise ValueError("fixture failure")
        return original(source, language, path)

    monkeypatch.setattr(quality, "extract_facts", fail_one)
    with pytest.warns(UserWarning, match="b.py"):
        rows = _edges(quality.export_edges(tmp_path))
    assert rows
    assert all(row["file"] != "b.py" for row in rows)


def test_whole_repo_failure_includes_traceback(tmp_path: Path, monkeypatch) -> None:
    _fixture_repo(tmp_path)

    def fail_prepare(*args):
        raise ValueError("whole repository failure")

    monkeypatch.setattr(quality, "prepare", fail_prepare)
    with pytest.raises(RuntimeError, match="whole repository failure") as error:
        quality.export_edges(tmp_path)
    assert "Traceback (most recent call last)" in str(error.value)


def test_all_fact_failures_raise(tmp_path: Path, monkeypatch) -> None:
    _fixture_repo(tmp_path)

    def fail_all(source, language, path=""):
        raise ValueError(f"fixture failure for {path}")

    monkeypatch.setattr(quality, "extract_facts", fail_all)
    with (
        pytest.warns(UserWarning),
        pytest.raises(RuntimeError, match="all 3 source files"),
    ):
        quality.export_edges(tmp_path)


def test_constructor_call_maps_to_initializer_declaration(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "constructor.py").write_text(
        "class Box:\n    def __init__(self):\n        pass\n\n"
        "def caller():\n    Box()\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        quality,
        "edges_for_file",
        lambda context, path: [
            {
                "callee": "constructor.py::Box.__init__#1",
                "kind": "resolved",
                "pass": "local",
            }
        ],
    )
    rows = _edges(quality.export_edges(tmp_path))
    edge = next(row for row in rows if row["name"] == "Box")
    assert edge["callee_name"] == "__init__"
    assert edge["callee_line"] == 2


def test_constructor_without_matching_initializer_uses_type_line(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "constructor.py").write_text(
        "class Box:\n    def __init__(self, value):\n        pass\n\n"
        "def caller():\n    Box()\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        quality,
        "extract_facts",
        lambda source, language, path: {
            "functions": [
                {
                    "id": "constructor.py::Box.__init__#1",
                    "name": "__init__",
                    "owner": "Box",
                    "line": 2,
                },
                {"id": "constructor.py::caller#1", "name": "caller", "line": 5},
            ],
            "types": [
                {"id": "constructor.py::Box#1", "name": "Box", "path": path, "line": 1}
            ],
            "call_sites": [
                {
                    "caller": "constructor.py::caller#1",
                    "name": "Box",
                    "line": 6,
                }
            ],
        },
    )
    monkeypatch.setattr(
        quality,
        "edges_for_file",
        lambda context, path: [
            {
                "callee": "constructor.py::Box#1",
                "kind": "resolved",
                "pass": "local",
            }
        ],
    )
    rows = _edges(quality.export_edges(tmp_path))
    edge = next(row for row in rows if row["name"] == "Box")
    assert edge["callee_name"] == "Box"
    assert edge["callee_line"] == 1


def test_edge_failure_warns_and_continues(tmp_path: Path, monkeypatch) -> None:
    _fixture_repo(tmp_path)
    original = quality.edges_for_file

    def fail_one(context, path):
        if path == "b.py":
            raise ValueError("edge fixture failure")
        return original(context, path)

    monkeypatch.setattr(quality, "edges_for_file", fail_one)
    with pytest.warns(UserWarning, match="b.py"):
        rows = _edges(quality.export_edges(tmp_path))
    assert rows
    assert all(row["file"] != "b.py" for row in rows)


def test_walk_skips_hidden_and_vendor_directories(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "def caller(): helper()\n", encoding="utf-8"
    )
    ignored = (
        ".hidden",
        "node_modules",
        "vendor",
        "target",
        "build",
        "dist",
        "__pycache__",
        ".git",
        "third_party",
    )
    for directory in ignored:
        nested = tmp_path / directory
        nested.mkdir()
        (nested / "app.py").write_text("def helper(): pass\n", encoding="utf-8")
    rows = _edges(quality.export_edges(tmp_path))
    assert {row["file"] for row in rows} == {"src/app.py"}


def test_runner_export_and_apply_edges_match_fixture(tmp_path: Path) -> None:
    from run import runner

    _fixture_repo(tmp_path)
    exported = runner._export_edges(quality, tmp_path, 5.0)
    rows = runner._load_edges(exported)
    record = {
        "repo": "fixture",
        "language": "python",
        "file": "a.py",
        "line": 6,
        "call_name": "unique",
        "ground_truth": "a.py::unique@3",
    }
    runner._apply_edges("fixture", [record], rows)
    assert record["measured_status"] == "resolved"
    assert record["measured_edge"] == "a.py::unique@3"


def test_exports_module_level_call_with_null_caller(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "def helper(): return 1\nhelper()\n", encoding="utf-8"
    )
    rows = _edges(quality.export_edges(tmp_path))
    assert [(row["caller"], row["kind"], row["site_line"]) for row in rows] == [
        (None, "resolved", 2)
    ]


def test_java_null_caller_calls_stay_unexported(tmp_path: Path) -> None:
    (tmp_path / "A.java").write_text(
        "class A {\n  static int helper() { return 1; }\n"
        "  static int x = helper();\n  int run() { return helper(); }\n}\n",
        encoding="utf-8",
    )
    rows = _edges(quality.export_edges(tmp_path))
    assert [row["site_line"] for row in rows] == [4]
