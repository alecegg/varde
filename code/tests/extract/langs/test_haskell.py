from varde_code.extract import extract_file
from varde_code.extract.langs import tables_for
from varde_code.model import EntityKind


def test_haskell_tables_and_entities():
    tables = tables_for("haskell")
    assert tables.function_scopes == frozenset({"function", "bind"})
    assert tables.type_scopes == frozenset(
        {"data_type", "newtype", "type_synonym", "class"}
    )
    assert EntityKind.IMPORT in tables.required_kinds
    assert EntityKind.CONTROL_FLOW in tables.required_kinds

    output = extract_file(
        "Main.hs",
        """module Main (main, Foo(..)) where
import qualified Data.Map as M
class Show a where show :: a -> String
data Foo = Foo Int
instance Show Foo where show (Foo x) = M.show x
value = 1
f x = if x > 0 then M.lookup x else error "missing"
""",
        "haskell",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.IMPORT, "Data/Map") in pairs
    assert (EntityKind.EXPORT, "Foo(..)") in pairs
    assert (EntityKind.INTERFACE, "Show") in pairs
    assert (EntityKind.CLASS, "Foo") in pairs
    assert (EntityKind.IMPLEMENTS, "Show") in pairs
    assert (EntityKind.PARAMETER, "x") in pairs
    assert (EntityKind.MEMBER_ACCESS, "show") in pairs
    assert (EntityKind.CALL, "lookup") in pairs
    assert (EntityKind.THROW, "error") in pairs
    assert (EntityKind.CONTROL_FLOW, "conditional") in pairs
    assert (EntityKind.LITERAL, '"missing"') in pairs


def test_haskell_clause_functions_and_pattern_parameters():
    output = extract_file("Main.hs", "choose 0 = False\nchoose n = True\n", "haskell")
    functions = [
        entity for entity in output.entities if entity.kind == EntityKind.FUNCTION
    ]
    params = [
        entity.name for entity in output.entities if entity.kind == EntityKind.PARAMETER
    ]
    assert [entity.name for entity in functions] == ["choose", "choose"]
    assert params == ["n"]
