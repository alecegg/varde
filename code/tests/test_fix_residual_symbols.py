from pathlib import Path

from varde_code.extract.provider import extract_file
from varde_code.model import SymbolKind


def test_rust_struct_expression_path_is_a_reference():
    source = """fn create(input: Value) {
    let event = EventBody::ItemAdded(flog::ItemAdded { value: input });
}
fn select(mode: FrictionAddMode) {
    match mode {
        FrictionAddMode::Create { .. } => (),
    }
}
"""

    output = extract_file(Path("store.rs"), source, "rust")
    references = [
        symbol.name for symbol in output.symbols if symbol.kind == SymbolKind.REFERENCE
    ]

    assert references.count("flog") == 1
    assert references.count("FrictionAddMode") == 1


def test_rust_scoped_type_path_matches_reference_context():
    source = "fn parse(input: serde_json::Value) -> serde_json::Value { input }\n"

    output = extract_file(Path("parse.rs"), source, "rust")
    references = [
        symbol.name for symbol in output.symbols if symbol.kind == SymbolKind.REFERENCE
    ]

    assert references.count("serde_json") == 2
    assert "Value" not in references


def test_typescript_import_names_are_bindings():
    source = """import React, { useState as state, useEffect } from "react";
import * as hooks from "hooks";
"""

    output = extract_file(Path("panel.ts"), source, "typescript")
    bindings = [
        symbol.name for symbol in output.symbols if symbol.kind == SymbolKind.BINDING
    ]
    references = [
        symbol.name for symbol in output.symbols if symbol.kind == SymbolKind.REFERENCE
    ]

    assert set(bindings) == {"React", "state", "useEffect", "hooks"}
    assert references == ["useState"]


def test_go_parameter_name_remains_a_reference():
    source = "package sample\nfunc render(value string) string { return value }\n"

    output = extract_file(Path("sample.go"), source, "go")
    references = [
        symbol.name for symbol in output.symbols if symbol.kind == SymbolKind.REFERENCE
    ]

    assert references.count("value") == 2


def test_scala_annotation_type_arguments_are_not_references():
    source = "trait Semigroup[@sp(Int, Long, Float, Double) A]\n"

    output = extract_file(Path("Semigroup.scala"), source, "scala")
    references = [
        symbol.name for symbol in output.symbols if symbol.kind == SymbolKind.REFERENCE
    ]

    assert "Long" not in references


def test_tsx_type_qualified_name_is_not_a_reference():
    source = "function render(): JSX.Element { return <div />; }\n"

    output = extract_file(Path("render.tsx"), source, "tsx")
    references = [
        symbol.name for symbol in output.symbols if symbol.kind == SymbolKind.REFERENCE
    ]

    assert "JSX" not in references
