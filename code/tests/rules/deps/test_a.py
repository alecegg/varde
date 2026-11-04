import sqlite3
from importlib import import_module
from pathlib import Path

from varde_code.model import Entity, EntityKind, ExtractOutput, Span
from varde_code.rules.dependency_facts import c_cpp, python, rust
from varde_code.rules.dependency_facts.types import FactInput

prepare_facts = import_module("varde_code.rules.dependency_facts.prepare")


def specs(text):
    return [
        (item.spec, item.guarded, item.attribute_form)
        for item in python.scan_imports(text)
    ]


def test_python_import_forms_match_extractor_specifiers():
    text = """from . import attrname
from . import sub
from .sub import thing
from ..pkg.sub import thing as t2
import os.path
import pkg.sub, other as o
from pkg import thing
"""
    assert [spec for spec, _, _ in specs(text)] == [
        "./attrname",
        "./sub",
        "./sub",
        "./../pkg/sub",
        "os/path",
        "pkg/sub",
        "other",
        "pkg",
    ]


def test_python_attribute_forms_are_only_appended_relative_forms():
    got = specs("from . import x\nfrom .mod import y\nfrom pkg import z\n")
    assert got == [("./x", False, True), ("./mod", False, False), ("pkg", False, False)]


def test_python_type_only_and_import_error_guards_are_flagged():
    text = """if TYPE_CHECKING:
    from . import typed
try:
    from . import optional
except ImportError:
    from . import fallback
try:
    from . import required
except ValueError:
    pass
"""
    assert [guarded for _, guarded, _ in specs(text)] == [True, True, True, False]


def test_python_module_paths_are_identifier_segments():
    assert all(python.is_module_path(value) for value in ("pkg", "pkg/sub", "a_b/c1"))
    assert not any(
        python.is_module_path(value)
        for value in ("", "/pkg", "pkg/", "pkg//sub", "a-b", "pkg/x.py", "a.b")
    )


def test_python_module_candidates_and_package_roots():
    assert python.module_candidates("pkg/sub") == ["pkg/sub.py", "pkg/sub/__init__.py"]
    assert all(python.is_source_root(value) for value in ("", "src", "lib/crewai/src"))
    assert not any(
        python.is_source_root(value)
        for value in ("plugins/platforms", "libs/langgraph", "srcx", "mysrc")
    )


def flags(text):
    return [
        (item.spec, item.quoted, item.conditional) for item in c_cpp.scan_includes(text)
    ]


def test_cpp_whole_file_guard_is_not_conditional():
    text = '#ifndef X_H\n#define X_H\n#include "a.h"\n#include <b.h>\n#endif\n'
    assert flags(text) == [("a.h", True, False), ("b.h", False, False)]


def test_cpp_nested_conditionals_and_non_guards_are_conditional():
    guarded = '#ifndef X_H\n#define X_H\n#ifdef Y\n#include "a.h"\n#endif\n#endif\n'
    trailing = '#ifndef X_H\n#define X_H\n#endif\n#include "a.h"\n'
    not_guard = '#ifndef X_H\n#include "a.h"\n#endif\n'
    assert flags(guarded) == [("a.h", True, True)]
    assert flags(trailing) == [("a.h", True, False)]
    assert flags(not_guard) == [("a.h", True, True)]


def test_cpp_comments_and_continuations_are_handled():
    text = (
        '/* #include "no.h" */ // #include "no2.h"\n#  include "yes.h" // c\n'
        '#define X \\\n #include "no3.h"\n'
    )
    assert flags(text) == [("yes.h", True, False)]


def guarded_specs(source, tmp_path):
    root = (
        __import__("varde_code.parse", fromlist=["parse_source"])
        .parse_source("rust", source)
        .root
    )
    # A small provider whose entity spans are supplied from the same tree walk.
    imports = []
    for node in rust.walk(root):
        if node.type in {"use_declaration", "mod_item"}:
            text = node.text.decode("utf-8")
            name = text.strip()
            if node.type == "use_declaration":
                name = name.removeprefix("use ").removesuffix(";").strip()
            elif (
                node.prev_sibling is not None
                and node.prev_sibling.type == "attribute_item"
            ):
                attribute = node.prev_sibling.text.decode("utf-8")
                if attribute.startswith("#[path"):
                    name = f"{attribute} {name.removesuffix(';')}"
            imports.append(
                Entity(
                    EntityKind.IMPORT,
                    name,
                    0,
                    Span(node.start_byte, node.end_byte, 1, 0, 1, 0),
                )
            )

    class Provider:
        def extract(self, path: Path, source: str, language: str) -> ExtractOutput:
            return ExtractOutput(entities=imports)

    physical = tmp_path / "sample.rs"
    physical.write_text(source)
    file = rust.FileRow(1, "sample.rs", "sample.rs", physical)
    input = FactInput(
        [file],
        [rust.ImportRow(i + 1, 1, entity.name) for i, entity in enumerate(imports)],
        [],
    )
    return rust.cfg_guarded_imports(input, Provider()).get(1, set())


def test_rust_cfg_guarded_modules_and_uses_are_collected(tmp_path):
    source = """#[cfg(test)]
mod tests {
    use crate::extract;
}

#[cfg(feature = "extra")]
#[path = "custom.rs"]
mod custom;

mod plain;
use crate::other;
"""
    specs = guarded_specs(source, tmp_path)
    assert "crate::extract" in specs
    assert '#[path = "custom.rs"] mod custom' in specs
    assert "crate::other" not in specs


def test_rust_direct_cfg_attribute_on_use_is_collected(tmp_path):
    specs = guarded_specs(
        "#[cfg(unix)]\nuse crate::unix_only::Thing;\nuse crate::always::Thing;\n",
        tmp_path,
    )
    assert "crate::unix_only::Thing" in specs
    assert "crate::always::Thing" not in specs


def test_rust_mod_segments_only_accept_module_declarations():
    assert rust.mod_segments("mod a::b") == ["a", "b"]
    assert rust.mod_segments('#[path = "x.rs"] mod a') is None
    assert rust.mod_segments("crate::a::B") is None


class _NeverExtract:
    def extract(self, path, source, language):
        raise AssertionError(f"unexpected extraction for {path}")


def _dependency_facts(files, entities, edges, root):
    """Run the public prepare() pipeline and return its persisted facts."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE files(
            id INTEGER PRIMARY KEY, path TEXT,
            is_test_path INTEGER, is_tooling_path INTEGER
        );
        CREATE TABLE entities(
            id INTEGER PRIMARY KEY, file_id INTEGER, kind INTEGER,
            name TEXT, body_shape TEXT
        );
        CREATE TABLE resolved_edges(
            id INTEGER PRIMARY KEY, from_file_id INTEGER, from_entity_id INTEGER,
            to_file_id INTEGER, kind INTEGER, resolved INTEGER
        );
    """)
    conn.executemany("INSERT INTO files VALUES (?,?,?,?)", files)
    conn.executemany("INSERT INTO entities VALUES (?,?,?,?,?)", entities)
    conn.executemany("INSERT INTO resolved_edges VALUES (?,?,?,?,?,?)", edges)
    prepare_facts.prepare(conn, root, _NeverExtract())
    rows = conn.execute(
        "SELECT from_file_id, from_unit, to_file_id, to_unit, kind, certainty, "
        "source_entity_id, specifier FROM temp.dependency_facts "
        "ORDER BY from_file_id, to_unit"
    ).fetchall()
    conn.close()
    return rows


def test_dependency_repository_paths_are_lexical_across_symlinks(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.js"
    outside.write_text("export {}\n", encoding="utf-8")
    (root / "alias.js").symlink_to(outside)
    (root / "app.js").write_text("import './alias';\n", encoding="utf-8")

    facts = _dependency_facts(
        files=[(1, "app.js", 0, 0), (2, "alias.js", 0, 0)],
        entities=[(1, 1, EntityKind.IMPORT.value, "./alias", "")],
        edges=[],
        root=root,
    )

    assert facts == [(1, "app.js", 2, "alias.js", 1, "certified", 1, "./alias")]


def test_removed_go_dependency_target_is_ignored(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.go").write_text("package a\n", encoding="utf-8")

    facts = _dependency_facts(
        files=[(1, "a.go", 0, 0), (2, "b.go", 0, 0)],
        entities=[(1, 1, EntityKind.IMPORT.value, "example/b", "")],
        edges=[(1, 1, 1, 2, 1, 1)],
        root=root,
    )

    assert facts == []


def test_dependency_extension_aliases_preserve_original_case(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.js").write_text("import './mod.JS';\n", encoding="utf-8")
    (root / "src" / "mod.JS").write_text("export {}\n", encoding="utf-8")

    facts = _dependency_facts(
        files=[(1, "src/app.js", 0, 0), (2, "src/mod.JS", 0, 0)],
        entities=[(1, 1, EntityKind.IMPORT.value, "./mod.JS", "")],
        edges=[],
        root=root,
    )

    assert facts == [(1, "src/app.js", 2, "src/mod.JS", 1, "certified", 1, "./mod.JS")]


def test_dependency_extension_aliases_fall_back_to_typescript(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.js").write_text("import './mod.JS';\n", encoding="utf-8")
    (root / "src" / "mod.ts").write_text("export {}\n", encoding="utf-8")

    facts = _dependency_facts(
        files=[(1, "src/app.js", 0, 0), (2, "src/mod.ts", 0, 0)],
        entities=[(1, 1, EntityKind.IMPORT.value, "./mod.JS", "")],
        edges=[],
        root=root,
    )

    assert facts == [(1, "src/app.js", 2, "src/mod.ts", 1, "certified", 1, "./mod.JS")]
