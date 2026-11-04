from varde_code.extract import extract_file
from varde_code.extract.langs import tables_for
from varde_code.model import EntityKind


def test_kotlin_tables_and_entities():
    tables = tables_for("kotlin")
    assert tables.function_scopes == frozenset(
        {"function_declaration", "getter", "setter"}
    )
    assert tables.type_scopes == frozenset(
        {
            "class_declaration",
            "object_declaration",
            "companion_object",
            "object_literal",
        }
    )
    assert EntityKind.FUNCTION in tables.required_kinds
    assert EntityKind.RESPONSE in tables.required_kinds

    output = extract_file(
        "Sample.kt",
        """package sample
import kotlin.collections.List as Items
public interface Store
public class Sample : Base(), Store {
  val count = 3
  fun run(input: String) {
    try { if (count > 0) call.service(input) else return }
    catch (error: Exception) { throw error }
    call.respondText("ok")
  }
}
""",
        "kotlin",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.IMPORT, "kotlin/collections/List") in pairs
    assert (EntityKind.CLASS, "Sample") in pairs
    assert (EntityKind.INTERFACE, "Store") in pairs
    assert (EntityKind.EXPORT, "Sample") in pairs
    assert (EntityKind.FUNCTION, "run") in pairs
    assert (EntityKind.PARAMETER, "input") in pairs
    assert (EntityKind.CALL, "call.service") in pairs
    assert (EntityKind.MEMBER_ACCESS, "service") in pairs
    assert (EntityKind.RESPONSE, "call.respondText") in pairs
    assert (EntityKind.CATCH, "error") in pairs
    assert (EntityKind.THROW, "error") in pairs


def test_kotlin_control_flow_and_inheritance():
    output = extract_file(
        "Sample.kt",
        "class Child : Base(), First, second.Third { fun f() { "
        "if (x) f() else g(); val x = 1 } }",
        "kotlin",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.EXTENDS, "Base") in pairs
    assert (EntityKind.IMPLEMENTS, "First") in pairs
    assert (EntityKind.IMPLEMENTS, "second.Third") in pairs
    assert (EntityKind.CONTROL_FLOW, "if_expression") in pairs
    assert (EntityKind.CONTROL_FLOW, "else_branch") in pairs
