from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "select_changed_test_modules.py"
)
loader = SourceFileLoader("select_changed_test_modules", str(SCRIPT))
spec = spec_from_loader(loader.name, loader)
assert spec is not None
selector = module_from_spec(spec)
loader.exec_module(selector)


def test_changed_module_includes_transitive_reverse_dependents():
    workspace_modules = ["core", "data", "workflow", "runner", "app"]
    dependencies = {
        "core": set(),
        "data": {"core"},
        "workflow": {"core", "data"},
        "runner": {"core", "data", "workflow"},
        "app": {"workflow"},
    }

    assert selector.select_modules(
        ["data/src/store.py"], dependencies, workspace_modules, workspace_modules
    ) == ["data", "workflow", "runner", "app"]


def test_unmapped_changes_select_every_test_fast_module():
    modules = ["core", "data", "app"]
    assert selector.select_modules(["justfile"], {}, modules, modules) == modules


def test_empty_changes_select_every_test_fast_module():
    modules = ["core", "data", "app"]
    assert selector.select_modules([], {}, modules, modules) == modules


def test_core_and_layers_changes_select_every_module():
    modules = ["core", "data", "app"]
    for changed in (["core/src/layout.py"], ["layers.toml"]):
        assert selector.select_modules(changed, {}, modules, modules) == modules


def test_dev_is_a_pytest_module_when_its_tests_are_discoverable():
    layers = selector._layers(selector.ROOT)
    assert "dev" in selector._test_modules(selector.ROOT, layers)


def test_module_dependencies_include_declared_couplings():
    layers = selector._layers(selector.ROOT)
    dependencies = selector._module_dependencies(selector.ROOT, layers)
    assert "workflow" in dependencies["app"]
