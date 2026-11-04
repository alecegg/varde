import sys
import types

import pytest
from varde_code.quality_resolve import digest_for_file, edges_for_file, prepare


def _language(monkeypatch, binding):
    package_name = "varde_code.quality_resolve.langs"
    package = types.ModuleType(package_name)
    package.__path__ = []
    module = types.ModuleType(f"{package_name}.csharp")
    attribute = "import_bindings"
    setattr(module, attribute, lambda *args: [binding])
    monkeypatch.setitem(sys.modules, package_name, package)
    monkeypatch.setitem(sys.modules, module.__name__, module)


def _facts(methods):
    return {
        "src/Main.cs": {
            "imports": [{"module": "Q.B", "line": 1}],
            "call_sites": [
                {"caller": "main", "name": "Work", "arity": 0, "receiver_text": "Alias"}
            ],
        },
        "src/B.cs": {"functions": methods},
        "src/Other.cs": {"functions": [{"id": "other", "name": "Other"}]},
    }


def test_owner_binding_resolves_only_methods_of_declared_type(monkeypatch):
    _language(
        monkeypatch,
        {"path": "src/B.cs", "names": [], "binding": "Alias", "owner": "B"},
    )
    facts = _facts(
        [
            {"id": "b-work", "name": "Work", "owner": "B", "params": 0},
            {"id": "c-work", "name": "Work", "owner": "C", "params": 0},
        ]
    )
    assert edges_for_file(prepare(facts, facts), "src/Main.cs")[0]["callee"] == "b-work"


def test_binding_without_owner_keeps_module_function_rule(monkeypatch):
    _language(monkeypatch, {"path": "src/B.cs", "names": [], "binding": "Alias"})
    facts = _facts(
        [
            {"id": "b-work", "name": "Work", "owner": "B", "params": 0},
            {"id": "module-work", "name": "Work", "params": 0},
        ]
    )
    assert (
        edges_for_file(prepare(facts, facts), "src/Main.cs")[0]["callee"]
        == "module-work"
    )


@pytest.mark.parametrize("owner", ["", None, 1, False])
def test_invalid_owner_raises_named_type_error(monkeypatch, owner):
    _language(
        monkeypatch,
        {"path": "src/B.cs", "names": [], "binding": "Alias", "owner": owner},
    )
    facts = _facts([])
    with pytest.raises(TypeError, match=r"csharp import_bindings.*Q.B"):
        prepare(facts, facts)


def test_owner_digest_tracks_only_that_types_methods(monkeypatch):
    _language(
        monkeypatch,
        {"path": "src/B.cs", "names": [], "binding": "Alias", "owner": "B"},
    )
    before = _facts(
        [
            {"id": "b-work", "name": "Work", "owner": "B", "params": 0},
            {"id": "c-work", "name": "Other", "owner": "C", "params": 0},
        ]
    )
    method_change = _facts(
        [
            {"id": "b-work", "name": "Work", "owner": "B", "params": 1},
            {"id": "c-work", "name": "Other", "owner": "C", "params": 0},
        ]
    )
    unrelated_change = _facts(
        [
            {"id": "b-work", "name": "Work", "owner": "B", "params": 0},
            {"id": "c-work", "name": "Other", "owner": "C", "params": 1},
        ]
    )
    original = prepare(before, before)
    assert digest_for_file(original, "src/Main.cs") != digest_for_file(
        prepare(method_change, method_change), "src/Main.cs"
    )
    assert digest_for_file(original, "src/Main.cs") == digest_for_file(
        prepare(unrelated_change, unrelated_change), "src/Main.cs"
    )
    assert digest_for_file(original, "src/Other.cs") == digest_for_file(
        prepare(method_change, method_change), "src/Other.cs"
    )
