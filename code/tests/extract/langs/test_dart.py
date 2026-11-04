from varde_code.extract import extract_file
from varde_code.extract.langs import tables_for
from varde_code.model import EntityKind


def test_dart_tables_and_entities():
    tables = tables_for("dart")
    assert tables.function_scopes
    assert "class_definition" in tables.type_scopes
    assert EntityKind.EXPORT in tables.required_kinds

    output = extract_file(
        "sample.dart",
        (
            "import 'base.dart'; export 'api.dart'; abstract class Animal "
            "extends Base with Walker implements Runnable { int legs = 4; "
            "void speak(String sound) { pet.call(sound); if (true) return; } } "
            "mixin Walker {}"
        ),
        "dart",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.IMPORT, "base.dart") in pairs
    assert (EntityKind.EXPORT, "api.dart") in pairs
    assert (EntityKind.CLASS, "Animal") in pairs
    assert (EntityKind.INTERFACE, "Walker") in pairs
    assert (EntityKind.EXTENDS, "Base") in pairs
    assert (EntityKind.IMPLEMENTS, "Runnable") in pairs
    assert (EntityKind.FUNCTION, "speak") in pairs
    assert (EntityKind.PARAMETER, "sound") in pairs
    assert (EntityKind.CALL, "call") in pairs
    assert (EntityKind.LITERAL, "4") in pairs
    assert (EntityKind.CONTROL_FLOW, "if_statement") in pairs
