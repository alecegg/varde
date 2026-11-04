import sys
import types

import pytest
from varde_code.quality_resolve import edges_for_file, prepare


def _language(monkeypatch, bindings):
    package_name = "varde_code.quality_resolve.langs"
    package = types.ModuleType(package_name)
    package.__path__ = []
    module = types.ModuleType(f"{package_name}.python")
    attribute = "import_bindings"
    setattr(module, attribute, bindings)
    monkeypatch.setitem(sys.modules, package_name, package)
    monkeypatch.setitem(sys.modules, module.__name__, module)


def _facts(import_spec, sites, target_functions):
    return {
        "src/main.py": {"imports": [import_spec], "call_sites": sites},
        "src/target.py": {"functions": target_functions},
        "src/other.py": {"functions": [{"id": "other-work", "name": "work"}]},
    }


def test_imported_name_is_resolved_only_when_binding_exposes_it(monkeypatch):
    _language(
        monkeypatch,
        lambda *args: [{"path": "src/target.py", "names": ["work"], "binding": None}],
    )
    facts = _facts(
        {"module": "custom", "line": 1},
        [{"name": "work"}, {"name": "other"}],
        [{"id": "work", "name": "work"}, {"id": "other", "name": "other"}],
    )
    edges = edges_for_file(prepare(facts, facts), "src/main.py")
    assert [(edge["kind"], edge["callee"]) for edge in edges] == [
        ("resolved", "work"),
        ("opaque", None),
    ]
    assert edges[0]["pass"] == "imported"  # noqa: S105 - Resolver pass labels are fixture values, not credentials.


def test_alias_resolves_visible_name_to_target_function(monkeypatch):
    _language(
        monkeypatch,
        lambda *args: [
            {
                "path": "src/target.py",
                "names": [],
                "aliases": {"w": "work"},
                "binding": None,
            }
        ],
    )
    facts = _facts(
        {"module": "custom", "line": 1},
        [{"name": "w"}],
        [{"id": "work", "name": "work"}],
    )
    edge = edges_for_file(prepare(facts, facts), "src/main.py")[0]
    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "resolved",
        "imported",
        "work",
    )


def test_alias_does_not_expose_target_name_as_visible_name(monkeypatch):
    _language(
        monkeypatch,
        lambda *args: [
            {
                "path": "src/target.py",
                "names": [],
                "aliases": {"w": "work"},
                "binding": None,
            }
        ],
    )
    facts = _facts(
        {"module": "custom", "line": 1},
        [{"name": "work"}],
        [{"id": "work", "name": "work"}],
    )
    edge = edges_for_file(prepare(facts, facts), "src/main.py")[0]
    assert (edge["kind"], edge["callee"]) == ("opaque", None)


def test_alias_keeps_multiple_target_candidates_ambiguous(monkeypatch):
    _language(
        monkeypatch,
        lambda *args: [
            {
                "path": path,
                "names": [],
                "aliases": {"w": "work"},
                "binding": None,
            }
            for path in ("src/target.py", "src/other.py")
        ],
    )
    facts = _facts(
        {"module": "custom", "line": 1},
        [{"name": "w"}],
        [{"id": "target-work", "name": "work"}],
    )
    facts["src/other.py"]["functions"] = [{"id": "other-work", "name": "work"}]
    edge = edges_for_file(prepare(facts, facts), "src/main.py")[0]
    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "ambiguous",
        "imported",
        None,
    )


def test_star_binding_exposes_each_function_in_bound_file(monkeypatch):
    _language(
        monkeypatch,
        lambda *args: [{"path": "src/target.py", "names": "*", "binding": None}],
    )
    facts = _facts(
        {"module": "custom", "line": 1},
        [{"name": "work"}],
        [{"id": "work", "name": "work"}],
    )
    edge = edges_for_file(prepare(facts, facts), "src/main.py")[0]
    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "resolved",
        "imported",
        "work",
    )


def test_receiver_binding_resolves_only_its_name(monkeypatch):
    _language(
        monkeypatch,
        lambda *args: [{"path": "src/target.py", "names": [], "binding": "mod"}],
    )
    facts = _facts(
        {"module": "custom", "line": 1},
        [{"name": "f", "receiver": "mod"}, {"name": "f", "receiver": "other"}],
        [{"id": "f", "name": "f"}],
    )
    edges = edges_for_file(prepare(facts, facts), "src/main.py")
    assert [(edge["kind"], edge["callee"]) for edge in edges] == [
        ("resolved", "f"),
        ("opaque", None),
    ]


def test_exact_type_import_binding_resolves_owned_methods(monkeypatch):
    _language(
        monkeypatch,
        lambda *args: [{"path": "src/target.py", "names": [], "binding": "B"}],
    )
    facts = _facts(
        {"module": "custom", "line": 1}, [{"name": "work", "receiver_text": "B"}], []
    )
    facts["src/target.py"] = {
        "types": [{"id": "type-b", "name": "B", "kind": "class"}],
        "functions": [{"id": "method", "name": "work", "owner": "B"}],
    }
    edge = edges_for_file(prepare(facts, facts), "src/main.py")[0]
    assert (edge["kind"], edge["callee"]) == ("resolved", "method")


def test_two_bound_files_keep_imported_name_ambiguous(monkeypatch):
    _language(
        monkeypatch,
        lambda *args: [
            {"path": "src/target.py", "names": ["work"], "binding": None},
            {"path": "src/other.py", "names": ["work"], "binding": None},
        ],
    )
    facts = _facts(
        {"module": "custom", "line": 1},
        [{"name": "work"}],
        [{"id": "target-work", "name": "work"}],
    )
    edge = edges_for_file(prepare(facts, facts), "src/main.py")[0]
    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "ambiguous",
        "imported",
        None,
    )


@pytest.mark.parametrize(
    "result",
    [
        (),
        [{"path": "missing.py", "names": [], "binding": None}],
        [{"path": "src/target.py", "names": [1], "binding": None}],
        [{"path": "src/target.py", "names": [], "binding": 1}],
        [{"path": "src/target.py", "names": []}],
        [{"path": "src/target.py", "binding": None}],
        [{"path": "src/target.py", "names": [], "binding": ""}],
        [{"path": "src/target.py", "names": [], "binding": None, "aliases": []}],
        [
            {
                "path": "src/target.py",
                "names": [],
                "binding": None,
                "aliases": {"": "work"},
            }
        ],
        [{"path": "src/target.py", "names": [], "binding": None, "aliases": {"w": ""}}],
        [
            {
                "path": "src/target.py",
                "names": [],
                "binding": None,
                "aliases": {1: "work"},
            }
        ],
        [{"path": "src/target.py", "names": [], "binding": None, "aliases": {"w": 1}}],
    ],
)
def test_malformed_import_bindings_raise_named_type_error(monkeypatch, result):
    _language(monkeypatch, lambda *args: result)
    facts = _facts({"module": "custom", "line": 1}, [], [])
    with pytest.raises(TypeError, match=r"python import_bindings.*custom"):
        prepare(facts, facts)


def test_import_binding_hook_exception_propagates(monkeypatch):
    error = RuntimeError("hook failed")

    def fail(*args):
        raise error

    _language(monkeypatch, fail)
    facts = _facts({"module": "custom", "line": 1}, [], [])
    with pytest.raises(RuntimeError, match="hook failed") as caught:
        prepare(facts, facts)
    assert caught.value is error


def test_empty_bindings_fall_back_to_import_targets(monkeypatch):
    _language(monkeypatch, lambda *args: [])
    module = sys.modules["varde_code.quality_resolve.langs.python"]
    attribute = "import_targets"
    setattr(module, attribute, lambda *args: ["src/target.py"])
    facts = _facts(
        {"module": "custom", "line": 1, "name": "target"},
        [{"name": "f", "receiver": "target"}],
        [{"id": "work", "name": "f"}],
    )
    edge = edges_for_file(prepare(facts, facts), "src/main.py")[0]
    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "resolved",
        "receiver",
        "work",
    )


def test_star_binding_does_not_shadow_same_file_definition(monkeypatch):
    _language(
        monkeypatch,
        lambda *args: [{"path": "src/target.py", "names": "*", "binding": None}],
    )
    facts = _facts(
        {"module": "custom", "line": 1},
        [{"name": "work"}],
        [{"id": "work", "name": "work"}],
    )
    facts["src/main.py"]["functions"] = [{"id": "local-work", "name": "work"}]
    edge = edges_for_file(prepare(facts, facts), "src/main.py")[0]
    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "resolved",
        "local",
        "local-work",
    )


def test_star_and_name_list_bindings_keep_duplicate_name_ambiguous(monkeypatch):
    _language(
        monkeypatch,
        lambda *args: [
            {"path": "src/target.py", "names": "*", "binding": None},
            {"path": "src/other.py", "names": ["work"], "binding": None},
        ],
    )
    facts = _facts(
        {"module": "custom", "line": 1},
        [{"name": "work"}],
        [{"id": "target-work", "name": "work"}],
    )
    facts["src/other.py"]["functions"] = [{"id": "other-work", "name": "work"}]
    edge = edges_for_file(prepare(facts, facts), "src/main.py")[0]
    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "ambiguous",
        "imported",
        None,
    )


def test_binding_change_invalidates_only_importing_file_digest(monkeypatch):
    result = [{"path": "src/target.py", "names": ["work"], "binding": None}]
    _language(monkeypatch, lambda *args: result)
    facts = _facts({"module": "custom", "line": 1}, [{"name": "work"}], [])
    first = prepare(facts, facts)
    result[0]["names"] = ["renamed"]
    second = prepare(facts, facts)
    assert first.input_digests["src/main.py"] != second.input_digests["src/main.py"]
    assert first.input_digests["src/target.py"] == second.input_digests["src/target.py"]
    assert first.input_digests["src/other.py"] == second.input_digests["src/other.py"]


def test_alias_target_edit_changes_only_importer_digest(monkeypatch):
    _language(
        monkeypatch,
        lambda *args: [
            {
                "path": "src/target.py",
                "names": [],
                "aliases": {"w": "work"},
                "binding": None,
            }
        ],
    )
    facts = _facts({"module": "custom", "line": 1}, [{"name": "w"}], [])
    facts["src/target.py"]["functions"] = [{"id": "work", "name": "work", "params": 1}]
    first = prepare(facts, facts)
    facts["src/target.py"]["functions"][0]["params"] = 2
    second = prepare(facts, facts)
    assert first.input_digests["src/main.py"] != second.input_digests["src/main.py"]
    assert first.input_digests["src/target.py"] != second.input_digests["src/target.py"]
    assert first.input_digests["src/other.py"] == second.input_digests["src/other.py"]
