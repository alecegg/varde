from varde_code.extract import extract_file
from varde_code.extract.langs import tables_for
from varde_code.model import EntityKind


def test_java_tables_and_entities():
    tables = tables_for("java")
    assert tables.function_scopes == frozenset(
        {
            "method_declaration",
            "constructor_declaration",
            "compact_constructor_declaration",
        }
    )
    assert tables.type_scopes == frozenset(
        {"class_declaration", "interface_declaration", "record_declaration"}
    )
    assert EntityKind.FUNCTION in tables.required_kinds
    assert EntityKind.ROUTE in tables.required_kinds

    output = extract_file(
        "Sample.java",
        """package sample;
import java.util.List;
@GetMapping("/items")
public class Sample {
  private int value = 3;
  public int run(String input) {
    try { response.setStatus(204); return service.client.call(input); }
    catch (RuntimeException error) { throw error; }
  }
}
""",
        "java",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.IMPORT, "java/util/List") in pairs
    assert (EntityKind.CLASS, "Sample") in pairs
    assert (EntityKind.EXPORT, "Sample") in pairs
    assert (EntityKind.FUNCTION, "run") in pairs
    assert (EntityKind.PARAMETER, "input") in pairs
    assert (EntityKind.CALL, "call") in pairs
    assert (EntityKind.MEMBER_ACCESS, "client") in pairs
    assert (EntityKind.RESPONSE, "setStatus") in pairs
    assert (EntityKind.ROUTE, "GetMapping") in pairs
    assert (EntityKind.DECORATOR, "GetMapping") in pairs
    assert (EntityKind.CATCH, "error") in pairs
    assert (EntityKind.THROW, "error") in pairs


def test_java_class_inheritance_and_lambda_boundary():
    output = extract_file(
        "Sample.java",
        "class Sample extends Base implements First, pkg.Second { "
        "Runnable task = () -> {}; }\n",
        "java",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.EXTENDS, "Base") in pairs
    assert (EntityKind.IMPLEMENTS, "First") in pairs
    assert (EntityKind.IMPLEMENTS, "pkg.Second") in pairs
    assert (EntityKind.CALLABLE_BOUNDARY, "") in pairs
