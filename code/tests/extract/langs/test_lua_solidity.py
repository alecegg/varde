from varde_code.extract import extract_file
from varde_code.extract.langs import tables_for
from varde_code.model import EntityKind


def _pairs(source: str, language: str) -> set[tuple[EntityKind, str]]:
    extension = "lua" if language == "lua" else "sol"
    output = extract_file(f"sample.{extension}", source, language)
    return {(entity.kind, entity.name) for entity in output.entities}


def test_lua_tables_and_entities():
    tables = tables_for("lua")
    assert tables.function_scopes == frozenset(
        {"function_declaration", "function_definition"}
    )
    assert tables.type_scopes == frozenset()
    assert tables.required_kinds == (
        EntityKind.FUNCTION,
        EntityKind.VARIABLE,
        EntityKind.PARAMETER,
        EntityKind.CALL,
        EntityKind.LITERAL,
        EntityKind.MEMBER_ACCESS,
        EntityKind.THROW,
        EntityKind.CONTROL_FLOW,
    )
    pairs = _pairs(
        'local function run(value) local count = 1; local x = require("app.util"); '
        'obj:save(value); if value then return count else error("bad") end end',
        "lua",
    )
    assert (EntityKind.FUNCTION, "run") in pairs
    assert (EntityKind.PARAMETER, "value") in pairs
    assert (EntityKind.VARIABLE, "count") in pairs
    assert (EntityKind.IMPORT, "app/util") in pairs
    assert (EntityKind.CALL, "obj:save") in pairs
    assert (EntityKind.MEMBER_ACCESS, "save") in pairs
    assert (EntityKind.THROW, '"bad"') in pairs
    assert (EntityKind.CONTROL_FLOW, "if_statement") in pairs


def test_solidity_tables_and_entities():
    tables = tables_for("solidity")
    assert tables.function_scopes == frozenset(
        {
            "function_definition",
            "modifier_definition",
            "constructor_definition",
            "fallback_receive_definition",
            "yul_function_definition",
        }
    )
    assert tables.type_scopes == frozenset(
        {"contract_declaration", "library_declaration", "interface_declaration"}
    )
    assert EntityKind.EXTENDS in tables.required_kinds
    pairs = _pairs(
        (
            'pragma solidity ^0.8.0; import "./Base.sol"; contract Store is Base, '
            "IStore { uint public count; function save(uint value) public { "
            'require(value > 0, "bad"); '
            "repo.write(value); if (value > 1) { emit Saved(value); } } }"
        ),
        "solidity",
    )
    assert (EntityKind.IMPORT, "./Base.sol") in pairs
    assert (EntityKind.CLASS, "Store") in pairs
    assert (EntityKind.EXTENDS, "Base") in pairs
    assert (EntityKind.IMPLEMENTS, "IStore") in pairs
    assert (EntityKind.VARIABLE, "count") in pairs
    assert (EntityKind.PARAMETER, "value") in pairs
    assert (EntityKind.THROW, "require") in pairs
    assert (EntityKind.MEMBER_ACCESS, "write") in pairs
    assert (EntityKind.CALL, "write") in pairs
    assert (EntityKind.CALL, "Saved") in pairs
    assert (EntityKind.CONTROL_FLOW, "if_statement") in pairs
