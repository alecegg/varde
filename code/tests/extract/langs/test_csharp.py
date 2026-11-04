from varde_code.extract import extract_file
from varde_code.extract.langs import tables_for
from varde_code.model import EntityKind


def test_csharp_tables_and_declarations():
    tables = tables_for("csharp")
    assert tables.function_scopes == frozenset(
        {
            "method_declaration",
            "constructor_declaration",
            "local_function_statement",
            "accessor_declaration",
            "operator_declaration",
            "conversion_operator_declaration",
            "destructor_declaration",
            "property_declaration",
            "indexer_declaration",
        }
    )
    assert tables.type_scopes == frozenset(
        {
            "class_declaration",
            "interface_declaration",
            "record_declaration",
            "struct_declaration",
        }
    )
    assert EntityKind.ROUTE in tables.required_kinds
    output = extract_file(
        "Sample.cs",
        """using System.Collections.Generic;
[ApiController]
public class Sample : Base, IFoo {
  public List<int> Values { get; set; }
  public int Run(string input) {
    try { if (input != null && Ready()) return service.Call(input); }
    catch (Exception error) { throw error; }
    return 0;
  }
}
""",
        "csharp",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.IMPORT, "System/Collections/Generic") in pairs
    assert (EntityKind.CLASS, "Sample") in pairs
    assert (EntityKind.EXPORT, "Sample") in pairs
    assert (EntityKind.EXTENDS, "Base") in pairs
    assert (EntityKind.IMPLEMENTS, "IFoo") in pairs
    assert (EntityKind.VARIABLE, "Values") in pairs
    assert (EntityKind.FUNCTION, "Run") in pairs
    assert (EntityKind.PARAMETER, "input") in pairs
    assert (EntityKind.CALL, "service.Call") in pairs
    assert (EntityKind.MEMBER_ACCESS, "Call") in pairs
    assert (EntityKind.CATCH, "error") in pairs
    assert (EntityKind.THROW, "error") in pairs
    assert (EntityKind.CONTROL_FLOW, "logical_and") in pairs
    assert (EntityKind.DECORATOR, "ApiController") in pairs


def test_csharp_minimal_api_and_callable_boundaries():
    output = extract_file(
        "Program.cs",
        (
            'app.MapGet("/items", () => Results.Ok(Load()));\n'
            "class Catalog { int Count { get { return Load(); } } "
            "void Run() { queue(delegate { Later(); }); } }"
        ),
        "csharp",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.ROUTE, "app.MapGet") in pairs
    assert (EntityKind.RESPONSE, "Results.Ok") in pairs
    assert (EntityKind.FUNCTION, "Count.get") in pairs
    assert (EntityKind.CALLABLE_BOUNDARY, "") in pairs
