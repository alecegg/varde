from varde_code.extract import extract_file
from varde_code.extract.langs import tables_for
from varde_code.model import EntityKind


def test_go_tables_and_entities():
    tables = tables_for("go")
    assert tables.function_scopes == frozenset(
        {"function_declaration", "method_declaration"}
    )
    assert tables.type_scopes == frozenset()
    assert tables.required_kinds == (
        EntityKind.FUNCTION,
        EntityKind.CLASS,
        EntityKind.INTERFACE,
        EntityKind.VARIABLE,
        EntityKind.PARAMETER,
        EntityKind.EXPORT,
        EntityKind.CALL,
        EntityKind.LITERAL,
        EntityKind.MEMBER_ACCESS,
        EntityKind.THROW,
        EntityKind.CONTROL_FLOW,
        EntityKind.ROUTE,
        EntityKind.RESPONSE,
    )
    output = extract_file(
        "sample.go",
        'package main\nimport "fmt"\ntype Store struct{}\n'
        "func (s *Store) Save(name string) { local := 1; fmt.Println(name); "
        'if local > 0 { panic("bad") } }\n',
        "go",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.FUNCTION, "Save") in pairs
    assert (EntityKind.CLASS, "Store") in pairs
    assert (EntityKind.VARIABLE, "local") in pairs
    assert (EntityKind.PARAMETER, "name") in pairs
    assert (EntityKind.EXPORT, "Store") in pairs
    assert (EntityKind.IMPORT, "fmt") in pairs
    assert (EntityKind.CALL, "fmt.Println") in pairs
    assert (EntityKind.MEMBER_ACCESS, "Println") in pairs
    assert (EntityKind.THROW, '"bad"') in pairs
    assert (EntityKind.CONTROL_FLOW, "if_statement") in pairs


def test_go_multi_names_and_control_flow():
    output = extract_file(
        "sample.go",
        "package p\nvar first, second int\nfunc f(a, b bool) { x, y := 1, 2; "
        "if a && b { return }; _ = x; _ = y }\n",
        "go",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.VARIABLE, "first") in pairs
    assert (EntityKind.VARIABLE, "second") in pairs
    assert (EntityKind.VARIABLE, "x") in pairs
    assert (EntityKind.VARIABLE, "y") in pairs
    assert (EntityKind.PARAMETER, "a") in pairs
    assert (EntityKind.PARAMETER, "b") in pairs
    assert (EntityKind.CONTROL_FLOW, "logical_and") in pairs
    assert (EntityKind.CALLABLE_BOUNDARY, "") in pairs or not any(
        entity.kind == EntityKind.CALLABLE_BOUNDARY for entity in output.entities
    )


def test_go_embedded_fields_and_if_legacy_nesting():
    output = extract_file(
        "sample.go",
        'package p\nimport "sync"\ntype Store struct { sync.RWMutex }\n'
        'func f(ok bool) { if ok { return } else { panic("bad") } }\n',
        "go",
    )
    entities = {
        (entity.kind, entity.name, entity.span.start_line, entity.span.end_line)
        for entity in output.entities
    }
    assert (EntityKind.EXTENDS, "sync.RWMutex", 3, 3) in entities
    assert (EntityKind.CONTROL_FLOW, "if_statement", 4, 4) in entities
    assert (EntityKind.CONTROL_FLOW, "legacy_nesting", 4, 4) in entities
    assert (EntityKind.CONTROL_FLOW, "else_branch", 4, 4) in entities
