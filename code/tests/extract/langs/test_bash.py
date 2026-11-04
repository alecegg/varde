from varde_code.extract import extract_file
from varde_code.extract.langs import tables_for
from varde_code.model import EntityKind


def test_bash_tables_and_entities():
    tables = tables_for("bash")
    assert tables.function_scopes == frozenset({"function_definition"})
    assert tables.type_scopes == frozenset()
    assert tables.required_kinds == (
        EntityKind.FUNCTION,
        EntityKind.VARIABLE,
        EntityKind.EXPORT,
        EntityKind.CALL,
        EntityKind.LITERAL,
        EntityKind.CONTROL_FLOW,
    )
    output = extract_file(
        "sample.sh",
        (
            'answer=42\nexport PUBLIC=1\nsource "lib.sh"\n'
            'work() { echo "ok"; }\nif true; then work; fi\n'
        ),
        "bash",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.VARIABLE, "answer") in pairs
    assert (EntityKind.EXPORT, "PUBLIC") in pairs
    assert (EntityKind.IMPORT, "lib.sh") in pairs
    assert (EntityKind.FUNCTION, "work") in pairs
    assert (EntityKind.CALL, "echo") in pairs
    assert (EntityKind.LITERAL, '"ok"') in pairs
    assert (EntityKind.CONTROL_FLOW, "if_statement") in pairs
