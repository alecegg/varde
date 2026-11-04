from varde_code.extract import extract_file
from varde_code.extract.langs import tables_for
from varde_code.model import EntityKind


def test_swift_tables_and_entities():
    tables = tables_for("swift")
    assert tables.function_scopes == frozenset(
        {
            "function_declaration",
            "init_declaration",
            "protocol_function_declaration",
            "computed_getter",
            "computed_setter",
        }
    )
    assert tables.type_scopes == frozenset(
        {"class_declaration", "protocol_declaration"}
    )
    assert EntityKind.FUNCTION in tables.required_kinds
    assert EntityKind.RESPONSE in tables.required_kinds

    output = extract_file(
        "Sample.swift",
        """import Foundation
public class Sample: Codable {
  var value = 3
  public func run(_ input: String) {
    if input.isEmpty { app.get("/items") { res.send(input) } }
    do { try work() } catch let error { print(error) }
  }
}
""",
        "swift",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.IMPORT, "Foundation") in pairs
    assert (EntityKind.CLASS, "Sample") in pairs
    assert (EntityKind.EXPORT, "Sample") in pairs
    assert (EntityKind.FUNCTION, "run") in pairs
    assert (EntityKind.PARAMETER, "input") in pairs
    assert (EntityKind.CALL, "app.get") in pairs
    assert (EntityKind.MEMBER_ACCESS, "get") in pairs
    assert (EntityKind.ROUTE, "app.get") in pairs
    assert (EntityKind.RESPONSE, "res.send") in pairs
    assert (EntityKind.CATCH, "error") in pairs


def test_swift_ambiguous_class_inheritance_is_implemented():
    output = extract_file("Sample.swift", "class Sample: Base, Codable {}\n", "swift")
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.IMPLEMENTS, "Base") in pairs
    assert (EntityKind.IMPLEMENTS, "Codable") in pairs
    assert not any(kind == EntityKind.EXTENDS for kind, _ in pairs)


def test_swift_protocol_inheritance_and_accessor_names():
    output = extract_file(
        "Sample.swift",
        "protocol Child: Parent {}\nstruct Settings { var value: Int { "
        "get { load() } set { save(newValue) } } }\n",
        "swift",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.EXTENDS, "Parent") in pairs
    assert (EntityKind.FUNCTION, "value.get") in pairs
    assert (EntityKind.FUNCTION, "value.set") in pairs


def test_swift_error_flow_and_closure_entities():
    output = extract_file(
        "Sample.swift",
        "func outer(_ a: Bool, _ b: Bool) { if a && b {} else if b {} ; "
        "let f = { return 1 }; do {} catch let error { throw error } }\n",
        "swift",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.CONTROL_FLOW, "logical_and") in pairs
    assert (EntityKind.CONTROL_FLOW, "elseif_statement") in pairs
    assert (EntityKind.CALLABLE_BOUNDARY, "") in pairs
    assert (EntityKind.THROW, "error") in pairs
