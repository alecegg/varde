import sys
import types

import pytest
from varde_code.quality_resolve import edges_for_file, prepare


def test_language_import_targets_hook_can_map_a_spec_to_a_file(monkeypatch):
    package_name = "varde_code.quality_resolve.langs"
    package = types.ModuleType(package_name)
    package.__path__ = []
    module_name = f"{package_name}.python"
    module = types.ModuleType(module_name)
    seen = {}

    def import_targets(spec, importer_path, file_set, context):
        seen.update(
            spec=spec,
            importer_path=importer_path,
            file_set=file_set,
            context=context,
        )
        return ["src/target.py"]

    attribute = "import_targets"
    setattr(module, attribute, import_targets)
    monkeypatch.setitem(sys.modules, package_name, package)
    monkeypatch.setitem(sys.modules, module_name, module)
    facts = {
        "src/main.py": {
            "imports": [{"module": "custom.module", "name": "work", "line": 1}],
            "functions": [{"id": "main", "name": "main", "params": 0}],
            "call_sites": [{"caller": "main", "name": "work", "arity": 0, "line": 2}],
        },
        "src/target.py": {"functions": [{"id": "work", "name": "work", "params": 0}]},
    }

    edge = edges_for_file(prepare(facts, facts), "src/main.py")[0]

    assert edge["kind"] == "resolved"
    assert edge["pass"] == "imported"  # noqa: S105 - Resolver pass labels are fixture values, not credentials.
    assert edge["callee"] == "work"
    assert seen == {
        "spec": {"module": "custom.module", "name": "work", "line": 1},
        "importer_path": "src/main.py",
        "file_set": ("src/main.py", "src/target.py"),
        "context": facts,
    }


def _hooked_module(monkeypatch, hook):
    package_name = "varde_code.quality_resolve.langs"
    package = types.ModuleType(package_name)
    package.__path__ = []
    module_name = f"{package_name}.python"
    module = types.ModuleType(module_name)
    attribute = "import_targets"
    setattr(module, attribute, hook)
    monkeypatch.setitem(sys.modules, package_name, package)
    monkeypatch.setitem(sys.modules, module_name, module)


def _import_facts():
    return {
        "src/main.py": {"imports": [{"module": "target", "name": "work", "line": 1}]},
        "src/target.py": {"functions": [{"id": "work", "name": "work"}]},
    }


def test_absent_language_package_uses_default_matcher(monkeypatch):
    def missing(name):
        raise ModuleNotFoundError(name, name=name)

    monkeypatch.setattr(
        "varde_code.quality_resolve.core.importlib.import_module", missing
    )
    facts = _import_facts()
    facts["src/main.py"]["call_sites"] = [{"name": "work"}]
    edge = edges_for_file(prepare(facts, facts), "src/main.py")[0]
    assert edge["kind"] == "resolved"
    assert edge["callee"] == "work"


def test_language_hook_exception_propagates(monkeypatch):
    def fail(*args):
        raise ValueError("hook failed")

    _hooked_module(monkeypatch, fail)
    facts = _import_facts()
    with pytest.raises(ValueError, match="hook failed"):
        prepare(facts, facts)


def test_nested_import_error_propagates(monkeypatch):
    def missing_dependency(name):
        raise ModuleNotFoundError("nested dependency", name="nested_dependency")

    monkeypatch.setattr(
        "varde_code.quality_resolve.core.importlib.import_module", missing_dependency
    )
    facts = _import_facts()
    with pytest.raises(ModuleNotFoundError, match="nested dependency"):
        prepare(facts, facts)


def test_invalid_hook_paths_fall_back_to_default_matcher(monkeypatch):
    _hooked_module(monkeypatch, lambda *args: ["outside.py"])
    facts = _import_facts()
    facts["src/main.py"]["call_sites"] = [{"name": "work"}]
    edge = edges_for_file(prepare(facts, facts), "src/main.py")[0]
    assert edge["kind"] == "resolved"
    assert edge["pass"] == "imported"  # noqa: S105 - Resolver pass labels are fixture values, not credentials.
    assert edge["callee"] == "work"


def test_hook_targets_change_resolution_digest(monkeypatch):
    selected = ["src/target.py"]
    _hooked_module(monkeypatch, lambda *args: selected)
    facts = _import_facts()
    facts["src/main.py"]["call_sites"] = [{"name": "work"}]
    first = prepare(facts, facts)
    selected[:] = ["src/other.py"]
    facts["src/other.py"] = {"functions": [{"id": "work-2", "name": "work"}]}
    second = prepare(facts, facts)
    assert first.input_digests["src/main.py"] != second.input_digests["src/main.py"]


def test_non_list_hook_result_raises_type_error(monkeypatch):
    _hooked_module(monkeypatch, lambda *args: ())
    facts = _import_facts()
    with pytest.raises(TypeError, match="must return a list"):
        prepare(facts, facts)
