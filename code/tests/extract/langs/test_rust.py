from varde_code.extract import extract_file
from varde_code.extract.langs import tables_for
from varde_code.model import EntityKind


def test_rust_tables_and_entities():
    tables = tables_for("rust")
    assert tables.function_scopes == frozenset(
        {"function_item", "function_signature_item", "closure_expression"}
    )
    assert tables.type_scopes == frozenset({"impl_item", "trait_item"})
    assert EntityKind.INTERFACE in tables.required_kinds
    output = extract_file(
        "sample.rs",
        'pub fn run(value: i32) { let answer = value + 1; println!("ok"); '
        "if value > 0 { work(); } }",
        "rust",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.FUNCTION, "run") in pairs
    assert (EntityKind.EXPORT, "run") in pairs
    assert (EntityKind.PARAMETER, "value") in pairs
    assert (EntityKind.VARIABLE, "answer") in pairs
    assert (EntityKind.CALL, "work") in pairs
    assert (EntityKind.LITERAL, '"ok"') in pairs
    assert (EntityKind.CONTROL_FLOW, "if_expression") in pairs


def test_rust_imports_and_pattern_bindings():
    output = extract_file(
        "sample.rs",
        "use std::fmt;\nfn f(pair: (i32, i32)) { let (left, right) = pair; }",
        "rust",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.IMPORT, "std::fmt") in pairs
    assert (EntityKind.PARAMETER, "pair") in pairs
    assert (EntityKind.VARIABLE, "left") in pairs
    assert (EntityKind.VARIABLE, "right") in pairs


def test_rust_declarations_control_flow_and_type_literals():
    source = """
pub trait Draw { fn draw(&self); }
struct Marker;
impl Draw for Marker { fn draw(&self) { let size: [u8; 4] = [1, 2, 3, 4]; } }
fn fail() { panic!(\"broken\"); }
fn decide(a: bool, b: bool) { if a && b { work(); } else { other(); } }
"""
    entities = extract_file("sample.rs", source, "rust").entities
    pairs = {(entity.kind, entity.name) for entity in entities}
    assert (EntityKind.INTERFACE, "Draw") in pairs
    assert (EntityKind.IMPLEMENTS, "Draw") in pairs
    assert (EntityKind.THROW, '"broken"') in pairs
    assert (EntityKind.CONTROL_FLOW, "logical_and") in pairs
    assert (EntityKind.CONTROL_FLOW, "legacy_nesting") in pairs
    assert (
        sum(
            entity.kind == EntityKind.LITERAL and entity.name == "4"
            for entity in entities
        )
        == 1
    )
