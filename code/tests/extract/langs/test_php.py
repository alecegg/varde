from varde_code.extract import extract_file, tables_for
from varde_code.model import EntityKind


def test_php_tables_and_entities():
    tables = tables_for("php")
    assert tables.function_scopes == frozenset(
        {"function_definition", "method_declaration"}
    )
    assert EntityKind.ROUTE in tables.required_kinds
    source = """<?php
namespace App;
use Foo\\Bar;
interface Contract {}
trait Shared { public function common() {} }
class Controller extends Base implements Contract {
    public function run(int $id) {
        $value = new Service();
        try { $value->load($id); } catch (\\Exception $error) { throw $error; }
        if ($id && true) { return view("items"); }
    }
}
Route::get("/items", [Controller::class, "run"]);
require_once "helpers.php";
"""
    output = extract_file("Controller.php", source, "php")
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.IMPORT, "Foo/Bar") in pairs
    assert (EntityKind.IMPORT, "helpers.php") in pairs
    assert (EntityKind.INTERFACE, "Contract") in pairs
    assert (EntityKind.CLASS, "Shared") in pairs
    assert (EntityKind.EXTENDS, "Base") in pairs
    assert (EntityKind.IMPLEMENTS, "Contract") in pairs
    assert (EntityKind.FUNCTION, "run") in pairs
    assert (EntityKind.PARAMETER, "id") in pairs
    assert (EntityKind.VARIABLE, "value") in pairs
    assert (EntityKind.CALL, "load") in pairs
    assert (EntityKind.MEMBER_ACCESS, "load") in pairs
    assert (EntityKind.CATCH, "error") in pairs
    assert (EntityKind.THROW, "$error") in pairs
    assert (EntityKind.CONTROL_FLOW, "logical_and") in pairs
