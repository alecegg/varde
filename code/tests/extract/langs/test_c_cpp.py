from varde_code.extract import extract_file
from varde_code.extract.langs import tables_for
from varde_code.model import EntityKind


def test_c_and_cpp_tables_and_entities():
    c_tables = tables_for("c")
    cpp_tables = tables_for("cpp")
    assert c_tables.function_scopes == frozenset({"function_definition"})
    assert "struct_specifier" in c_tables.type_scopes
    assert EntityKind.CONTROL_FLOW in c_tables.required_kinds
    assert EntityKind.CATCH in cpp_tables.required_kinds

    c_output = extract_file(
        "sample.c",
        (
            '#include "helper.h"\ntypedef struct Point { int x; } Point;\n'
            "int add(int x) { return helper(x) + point.x; }\n"
        ),
        "c",
    )
    c_pairs = {(entity.kind, entity.name) for entity in c_output.entities}
    assert (EntityKind.IMPORT, "helper.h") in c_pairs
    assert (EntityKind.CLASS, "Point") in c_pairs
    assert (EntityKind.FUNCTION, "add") in c_pairs
    assert (EntityKind.PARAMETER, "x") in c_pairs
    assert (EntityKind.CALL, "helper") in c_pairs
    assert (EntityKind.MEMBER_ACCESS, "x") in c_pairs
    assert (EntityKind.CONTROL_FLOW, "return_statement") in c_pairs

    cpp_output = extract_file(
        "sample.cpp",
        (
            "class Child : public Parent { int value; };\n"
            "int run(int x) { try { return helper(x); } "
            "catch (Error& error) { throw error; } }\n"
        ),
        "cpp",
    )
    cpp_pairs = {(entity.kind, entity.name) for entity in cpp_output.entities}
    assert (EntityKind.CLASS, "Child") in cpp_pairs
    assert (EntityKind.EXTENDS, "Parent") in cpp_pairs
    assert (EntityKind.FUNCTION, "run") in cpp_pairs
    assert (EntityKind.CATCH, "error") in cpp_pairs
    assert (EntityKind.THROW, "error") in cpp_pairs


def test_c_preprocessor_macros_and_control_flow():
    output = extract_file(
        "sample.c",
        (
            "#define LIMIT 8\n#define CHECK(x) ((x) && LIMIT)\n"
            "#if LIMIT\nint run(int x) { if (x && CHECK(x)) return 1; "
            "else return 0; }\n#endif\n"
        ),
        "c",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.VARIABLE, "LIMIT") in pairs
    assert (EntityKind.FUNCTION, "CHECK") in pairs
    assert (EntityKind.CONTROL_FLOW, "preproc_if") in pairs
    assert (EntityKind.CONTROL_FLOW, "logical_and") in pairs
    assert (EntityKind.CONTROL_FLOW, "if_statement") in pairs
    assert (EntityKind.CONTROL_FLOW, "else_branch") in pairs
    assert (EntityKind.CONTROL_FLOW, "legacy_nesting") in pairs


def test_cpp_qualified_methods_and_in_class_method_declarations():
    output = extract_file(
        "sample.cpp",
        "struct Box { int Get() const; };\n"
        "int Box::Get() const { if (ready() || done()) return 1; else return 0; }\n",
        "cpp",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.FUNCTION, "Get") in pairs
    assert (EntityKind.CONTROL_FLOW, "logical_or") in pairs
    assert (EntityKind.CONTROL_FLOW, "legacy_nesting") in pairs
    assert (EntityKind.CONTROL_FLOW, "else_branch") in pairs
