from varde_code.extract import extract_file
from varde_code.model import EntityKind, SymbolKind


def test_language_specific_identifier_leaves_are_references():
    cases = [
        ("sample.sh", "bash", 'value=1\nprintf "%s" "$value"\n', "value"),
        ("Sample.swift", "swift", "func use(_ value: Int) { print(value) }\n", "value"),
        ("sample.hs", "haskell", "main = print value\n", "value"),
        (
            "sample.php",
            "php",
            "<?php function useValue($value) { echo $value; }",
            "$value",
        ),
    ]

    for path, language, source, expected in cases:
        output = extract_file(path, source, language)
        assert any(
            symbol.kind == SymbolKind.REFERENCE and symbol.name == expected
            for symbol in output.symbols
        ), language


def test_generic_classification_skips_declared_and_parameter_names():
    output = extract_file(
        "sample.swift", "func use(_ value: Int) { print(value) }\n", "swift"
    )

    assert [symbol.name for symbol in output.symbols] == ["print", "value"]


def test_rust_scoped_path_name_is_a_reference():
    output = extract_file(
        "build.rs", 'use std::fs;\nfn main() { fs::read_dir("."); }\n', "rust"
    )

    assert any(
        symbol.kind == SymbolKind.REFERENCE and symbol.name == "fs"
        for symbol in output.symbols
    )


def test_bash_nested_boolean_operators_are_counted_once():
    output = extract_file("sample.sh", "if a && b && c; then echo ok; fi\n", "bash")

    logical_flows = [
        entity.name
        for entity in output.entities
        if entity.kind == EntityKind.CONTROL_FLOW and entity.name.startswith("logical_")
    ]
    assert logical_flows == ["logical_and", "logical_and"]


def test_rust_nested_boolean_operators_are_counted_once():
    output = extract_file(
        "sample.rs",
        "fn check(a: bool, b: bool, c: bool) -> bool { a && b && c }\n",
        "rust",
    )

    logical_flows = [
        entity.name
        for entity in output.entities
        if entity.kind == EntityKind.CONTROL_FLOW and entity.name.startswith("logical_")
    ]
    assert logical_flows == ["logical_and", "logical_and"]
