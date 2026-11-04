from __future__ import annotations

import json
from pathlib import Path

import pytest
from adapters import quality


def test_imported_call_resolves_to_imported_file(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "a.py").write_text(
        "from b import target\n\ndef caller():\n    target()\n", encoding="utf-8"
    )
    (tmp_path / "b.py").write_text("def target():\n    pass\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("def unrelated():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(
        quality,
        "import_specs",
        lambda *args: [{"module": "b", "name": "target", "line": 1}],
    )

    exported = quality.export_edges(tmp_path)
    rows = [json.loads(line) for line in exported.read_text().splitlines()]
    edge = next(row for row in rows if row["file"] == "a.py")

    assert edge["kind"] == "resolved"
    assert edge["callee_file"] == "b.py"
    assert edge["callee_name"] == "target"
    assert edge["pass"] == "imported"  # noqa: S105 - This is a non-secret resolver fixture label.


def test_module_import_does_not_resolve_bare_call(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "import b\n\ndef caller():\n    y()\n", encoding="utf-8"
    )
    (tmp_path / "b.py").write_text("def y():\n    pass\n", encoding="utf-8")

    exported = quality.export_edges(tmp_path)
    rows = [json.loads(line) for line in exported.read_text().splitlines()]
    edge = next(row for row in rows if row["file"] == "a.py")

    assert edge["kind"] != "resolved"
    assert edge["pass"] == "local"  # noqa: S105 - This is a non-secret resolver fixture label.


def test_aliased_import_resolves_bare_alias_call(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "a.py").write_text(
        "from b import target as alias\n\ndef caller():\n    alias()\n",
        encoding="utf-8",
    )
    (tmp_path / "b.py").write_text("def target():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(
        quality,
        "import_specs",
        lambda *args: [{"module": "b", "name": "target", "alias": "alias", "line": 1}],
    )

    exported = quality.export_edges(tmp_path)
    rows = [json.loads(line) for line in exported.read_text().splitlines()]
    edge = next(row for row in rows if row["file"] == "a.py")

    assert edge["kind"] == "resolved"
    assert edge["callee_file"] == "b.py"
    assert edge["callee_name"] == "target"


def test_star_import_resolves_unqualified_call(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "a.py").write_text(
        "from b import *\n\ndef caller():\n    y()\n", encoding="utf-8"
    )
    (tmp_path / "b.py").write_text("def y():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(
        quality,
        "import_specs",
        lambda *args: [{"module": "b", "name": "*", "line": 1}],
    )

    exported = quality.export_edges(tmp_path)
    rows = [json.loads(line) for line in exported.read_text().splitlines()]
    edge = next(row for row in rows if row["file"] == "a.py")

    assert edge["kind"] == "resolved"
    assert edge["callee_file"] == "b.py"
    assert edge["callee_name"] == "y"


def test_export_timeout_is_checked_between_files(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "a.py").write_text("def a(): pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def b(): pass\n", encoding="utf-8")
    original = quality.extract_facts
    clock = [0.0]
    monkeypatch.setattr(quality.time, "monotonic", lambda: clock[0])

    def slow_first(source: bytes, language: str, path: str = "") -> dict:
        facts = original(source, language, path)
        if path == "b.py":
            clock[0] = 1.0
        return facts

    monkeypatch.setattr(quality, "extract_facts", slow_first)

    with pytest.raises(TimeoutError, match="quality edge export exceeded timeout"):
        quality.export_edges(tmp_path, timeout_seconds=0.5)


def test_edge_write_timeout_removes_temporary_output(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "a.py").write_text("def caller(): target()\n", encoding="utf-8")
    output = tmp_path / "quality-edges-test.jsonl"
    monkeypatch.setattr(quality, "_new_output_path", lambda: output)
    clock = [0.0]
    monkeypatch.setattr(quality.time, "monotonic", lambda: clock[0])

    def slow_edges(path, facts_by_file, context, declarations):
        clock[0] = 1.0
        return [{"name": "target"}]

    monkeypatch.setattr(quality, "_file_edges", slow_edges)
    with pytest.raises(TimeoutError, match="quality edge export exceeded timeout"):
        quality.export_edges(tmp_path, timeout_seconds=0.5)
    assert not output.exists()
