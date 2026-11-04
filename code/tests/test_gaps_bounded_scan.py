import sqlite3

from varde_code.extract import extract_file
from varde_code.rules.correlate import TestPathLookup
from varde_code.rules.dependency_facts.rust import missing_facts
from varde_code.rules.dependency_facts.types import (
    EdgeRow,
    FactInput,
    FileRow,
    ImportRow,
)


def test_rust_test_attributes_mark_test_functions_and_cfg_test_helpers():
    source = """
#[test]
fn bare_test() {}

#[tokio::test]
async fn namespaced_test() {}

#[cfg(test)]
mod tests {
    fn helper() {}
}

#[cfg(feature = "fastest")]
fn production() {}

#[attest]
fn also_production() {}
"""

    functions = {
        entity.name: entity.is_test
        for entity in extract_file("src/lib.rs", source, "rust").entities
        if entity.kind.name == "FUNCTION"
    }

    assert functions == {
        "bare_test": True,
        "namespaced_test": True,
        "helper": True,
        "production": False,
        "also_production": False,
    }


def test_resolved_rust_inline_module_is_not_reported_missing(tmp_path):
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text("mod commands { mod common; }\n", encoding="utf-8")
    common = source.parent / "commands" / "common.rs"
    common.parent.mkdir()
    common.write_text("", encoding="utf-8")
    indexed_files = [
        FileRow(1, str(source), "src/lib.rs", source),
        FileRow(2, str(common), "src/commands/common.rs", common),
    ]
    imports = [ImportRow(8, 1, "mod common")]
    edges = [EdgeRow(1, 8, 2, True)]

    assert (
        missing_facts(
            FactInput(indexed_files, imports, edges),
            {file.id: file for file in indexed_files},
            {},
        )
        == []
    )


def test_pattern_test_path_lookup_matches_canonical_file_path(tmp_path):
    indexed_path = tmp_path / "repo" / "tests" / "fixture.rs"
    indexed_path.parent.mkdir(parents=True)
    indexed_path.write_text("", encoding="utf-8")
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE files(path TEXT, is_test_path INTEGER, is_tooling_path INTEGER)"
    )
    conn.execute("INSERT INTO files VALUES (?, 1, 0)", (str(indexed_path.resolve()),))
    scanned_path = tmp_path / "repo" / "src" / ".." / "tests" / "fixture.rs"

    assert TestPathLookup(conn).is_test_path(str(scanned_path))
