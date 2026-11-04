"""Enforce the Python workspace's package and import layering."""

from __future__ import annotations

import hashlib
import shutil
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from packaging.requirements import Requirement
from varde_core.layer_check import import_modules, load_layers, violates_level
from varde_core.layout import project_dirs

ROOT = Path(__file__).resolve().parents[2]
CORE = "varde-core"
APP = "varde"


def _project_paths(workspace: Path) -> dict[str, Path]:
    return project_dirs(workspace)


def _project_dependencies(metadata: dict[str, Any]) -> set[str]:
    project = metadata["project"]
    requirements = list(project.get("dependencies", []))
    requirements.extend(
        requirement
        for group in project.get("optional-dependencies", {}).values()
        for requirement in group
    )
    requirements.extend(
        requirement
        for group in metadata.get("dependency-groups", {}).values()
        for requirement in group
    )
    return {
        Requirement(requirement).name.lower().replace("_", "-")
        for requirement in requirements
    }


def _runtime_dependencies(metadata: dict[str, Any]) -> set[str]:
    return {
        Requirement(requirement).name.lower().replace("_", "-")
        for requirement in metadata["project"].get("dependencies", [])
    }


def _provider_projects(workspace: Path) -> set[str]:
    plugins = set()
    for package in project_dirs(workspace).values():
        path = package / "pyproject.toml"
        metadata = tomllib.loads(path.read_text())
        entry_points = metadata.get("project", {}).get("entry-points", {})
        if any(
            entry_points.get(group)
            for group in ("varde.modules", "varde.skills", "varde.agents")
        ):
            plugins.add(metadata["project"]["name"])
    return plugins


def _package_imports(
    workspace: Path, package_root: Path, project_name: str, project_names: set[str]
) -> tuple[set[str], set[str]]:
    module_to_project = {
        source.name: name
        for name, root in project_dirs(workspace).items()
        for source in (root / "src").glob("*")
        if name in project_names
        and source.is_dir()
        and (source / "__init__.py").is_file()
    }
    source_imports: set[str] = set()
    test_imports: set[str] = set()
    for directory, imports in (("src", source_imports), ("tests", test_imports)):
        for source in (package_root / directory).rglob("*.py"):
            signature = source.stat()
            roots = {
                module.split(".", 1)[0]
                for module in import_modules(
                    source, signature.st_mtime_ns, signature.st_size
                )
            }
            imports.update(
                module_to_project[root] for root in roots if root in module_to_project
            )
    source_imports.discard(project_name)
    test_imports.discard(project_name)
    return source_imports, test_imports


def violations(workspace: Path) -> list[str]:
    projects = _project_paths(workspace)
    known = set(projects)
    layers = load_layers(workspace / "layers.toml")
    workspace_modules = {
        package.relative_to(workspace).parts[0]: name
        for name, package in projects.items()
    }
    project_to_module = {
        name: module
        for name, package in projects.items()
        if (module := package.relative_to(workspace).parts[0]) in layers
    }
    graph: dict[str, set[str]] = {}
    test_imports: dict[str, set[str]] = {}
    for name, package in projects.items():
        metadata = tomllib.loads((package / "pyproject.toml").read_text())
        runtime_dependencies = _project_dependencies(metadata) & known
        source_imports, test_imports[name] = _package_imports(
            workspace, package, name, known
        )
        graph[name] = runtime_dependencies | source_imports

    errors: list[str] = []
    errors.extend(
        f"workspace module {module} is missing from layers.toml"
        for module in sorted(set(workspace_modules) - set(layers))
    )
    errors.extend(
        f"layers.toml module {module} is not a workspace project"
        for module in sorted(set(layers) - set(workspace_modules))
    )
    for package, dependencies in sorted(graph.items()):
        metadata = tomllib.loads((projects[package] / "pyproject.toml").read_text())
        module = project_to_module.get(package)
        if module is not None and layers[module]["dist"] != metadata["project"]["name"]:
            errors.append(
                f"layers.toml distribution for {module} does not match pyproject.toml"
            )
        declared = _runtime_dependencies(metadata) & known
        source_imports, _ = _package_imports(
            workspace, projects[package], package, known
        )
        errors.extend(
            f"{package} imports undeclared dependency {dependency}"
            for dependency in sorted(source_imports - declared)
        )
        unused_dependencies = declared - source_imports
        if package == APP:
            unused_dependencies -= _provider_projects(workspace)
        errors.extend(
            f"{package} declares unused dependency {dependency}"
            for dependency in sorted(unused_dependencies)
        )
        for dependency in sorted(dependencies):
            dependency_module = project_to_module.get(dependency)
            if (
                module is not None
                and dependency_module is not None
                and violates_level(layers, module, dependency_module)
            ):
                errors.append(f"{package} must not depend on {dependency}")

    for package, dependencies in sorted(test_imports.items()):
        for dependency in sorted(dependencies):
            module = project_to_module.get(package)
            dependency_module = project_to_module.get(dependency)
            if (
                module is not None
                and dependency_module is not None
                and violates_level(layers, module, dependency_module)
            ):
                errors.append(f"{package} tests must not depend on {dependency}")
    return errors


def backend_import_violations(workspace: Path) -> list[str]:
    errors = []
    for package, package_root in _project_paths(workspace).items():
        if package == "varde-data":
            continue
        for directory in ("src", "tests"):
            for source in (package_root / directory).rglob("*.py"):
                if source.relative_to(workspace).as_posix() == (
                    "workflow/tests/test_addresses_files.py"
                ):
                    continue
                signature = source.stat()
                modules = import_modules(
                    source, signature.st_mtime_ns, signature.st_size
                )
                private_backend = any(
                    module == "varde_data.backends"
                    or module.startswith("varde_data.backends.")
                    for module in modules
                )
                if private_backend:
                    errors.append(f"{package} imports varde_data.backends")
    return errors


def build_violations(workspace: Path) -> list[str]:
    projects = _project_paths(workspace)
    layers = load_layers(workspace / "layers.toml")
    distribution_to_module = {layer["dist"]: module for module, layer in layers.items()}
    errors = []
    for layer_module, layer in layers.items():
        project = projects.get(layer["dist"])
        if project is None:
            continue
        metadata = tomllib.loads((project / "pyproject.toml").read_text())
        for dependency in sorted(
            _runtime_dependencies(metadata) & set(distribution_to_module)
        ):
            dependency_module = distribution_to_module[dependency]
            if violates_level(layers, layer_module, dependency_module):
                errors.append(
                    f"{layer['dist']} build depends on non-lower {dependency}"
                )
    return errors


def _copy_workspace(destination: Path) -> Path:
    workspace = destination / "workspace"
    workspace.mkdir()
    shutil.copy2(ROOT / "layers.toml", workspace / "layers.toml")
    for source_package in project_dirs(ROOT).values():
        source_toml = source_package / "pyproject.toml"
        target_package = workspace / source_package.relative_to(ROOT)
        target_package.mkdir(parents=True)
        shutil.copy2(source_toml, target_package / "pyproject.toml")
        for directory in ("src", "tests"):
            for source in (source_package / directory).rglob("*.py"):
                target = target_package / source.relative_to(source_package)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.hardlink_to(source)
    return workspace


def _hard_link_hashes(workspace: Path) -> dict[Path, str]:
    hashes = {}
    for target in workspace.rglob("*"):
        if not target.is_file():
            continue
        source = ROOT / target.relative_to(workspace)
        if source.is_file() and target.samefile(source):
            hashes[source] = hashlib.sha256(source.read_bytes()).hexdigest()
    return hashes


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    workspace = _copy_workspace(tmp_path_factory.mktemp("dependency-rules"))
    original_hashes = _hard_link_hashes(workspace)
    yield workspace
    assert {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in original_hashes
    } == original_hashes


@pytest.fixture(autouse=True)
def restore_workspace(request: pytest.FixtureRequest) -> Iterator[None]:
    if "workspace" not in request.fixturenames:
        yield
        return

    workspace = request.getfixturevalue("workspace")
    original_dirs = {
        path.relative_to(workspace) for path in workspace.rglob("*") if path.is_dir()
    }
    original_files = {
        path.relative_to(workspace): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in workspace.rglob("*")
        if path.is_file()
    }
    yield

    current_files = {
        path.relative_to(workspace) for path in workspace.rglob("*") if path.is_file()
    }
    for relative in current_files - original_files.keys():
        (workspace / relative).unlink()

    for relative, signature in original_files.items():
        target = workspace / relative
        source = ROOT / relative
        if (
            not target.exists()
            or (
                target.stat().st_size,
                target.stat().st_mtime_ns,
            )
            != signature
        ):
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.hardlink_to(source)
            else:
                target.unlink()
                shutil.copy2(source, target)

    created_dirs = [
        path
        for path in workspace.rglob("*")
        if path.is_dir() and path.relative_to(workspace) not in original_dirs
    ]
    for directory in sorted(
        created_dirs, key=lambda path: len(path.parts), reverse=True
    ):
        directory.rmdir()


def _write_text(path: Path, text: str) -> None:
    path.unlink(missing_ok=True)
    path.write_text(text)


def _add_dependency(workspace: Path, package: str, dependency: str) -> None:
    path = _project_paths(workspace)[package] / "pyproject.toml"
    text = path.read_text()
    marker = "dependencies = ["
    start = text.index(marker) + len(marker)
    text = text[:start] + f'"{dependency}", ' + text[start:]
    _write_text(path, text)


def _add_import(workspace: Path, package: str, imported: str) -> None:
    package_root = _project_paths(workspace)[package]
    init = package_root / "src" / package.replace("-", "_") / "__init__.py"
    init.parent.mkdir(parents=True, exist_ok=True)
    _write_text(
        init,
        init.read_text() + f"\nimport {imported.replace('-', '_')}\n"
        if init.exists()
        else f"import {imported.replace('-', '_')}\n",
    )


@pytest.mark.parametrize(
    ("package", "dependency"),
    [
        (CORE, "varde-code"),
        ("varde-code", "varde-workflow"),
        ("varde-toz", "varde-code"),
        ("varde-runner", "varde"),
    ],
)
def test_dependency_edges_reject_seeded_violations(
    workspace: Path, package: str, dependency: str
) -> None:
    path = _project_paths(workspace)[package] / "pyproject.toml"
    original = path.read_text()
    _add_dependency(workspace, package, dependency)
    errors = violations(workspace)
    _write_text(path, original)
    assert errors


@pytest.mark.parametrize(
    ("package", "imported"),
    [
        (CORE, "varde_code"),
        ("varde-code", "varde_workflow"),
        ("varde-toz", "varde_code"),
        ("varde-runner", "varde"),
    ],
)
def test_import_edges_reject_seeded_violations(
    workspace: Path, package: str, imported: str
) -> None:
    package_root = _project_paths(workspace)[package]
    init = package_root / "src" / package.replace("-", "_") / "__init__.py"
    original = init.read_text() if init.exists() else None
    _add_import(workspace, package, imported)
    errors = violations(workspace)
    if original is None:
        init.unlink()
    else:
        _write_text(init, original)
    assert errors


def test_hand_written_package_importing_higher_layer_is_rejected(
    workspace: Path,
) -> None:
    tests = _project_paths(workspace)["varde-code"] / "tests"
    tests.mkdir(exist_ok=True)
    _write_text(tests / "test_fake_higher_layer.py", "import varde_workflow\n")
    errors = violations(workspace)
    (tests / "test_fake_higher_layer.py").unlink()
    assert "varde-code tests must not depend on varde-workflow" in errors


def test_optional_and_dependency_group_requirements_are_checked(
    workspace: Path,
) -> None:
    package = _project_paths(workspace)["varde-code"]
    path = package / "pyproject.toml"
    original = path.read_text()
    additions = '\n[project.optional-dependencies]\ntest = ["varde-workflow[x]~=1.0"]\n'
    additions += (
        "\n[dependency-groups]\ndev = [\"varde-toz; python_version >= '3.10'\"]\n"
    )
    _write_text(path, original + additions)
    errors = violations(workspace)
    _write_text(path, original)
    assert "varde-code must not depend on varde-workflow" in errors
    assert "varde-code must not depend on varde-toz" in errors


def test_workspace_follows_dependency_rules() -> None:
    assert violations(ROOT) == []


def test_runtime_build_dependencies_are_strictly_lower_layer() -> None:
    assert build_violations(ROOT) == []


def test_packages_do_not_import_data_backends() -> None:
    assert backend_import_violations(ROOT) == []


def test_data_backend_imports_reject_seeded_violations(workspace: Path) -> None:
    _add_import(workspace, "varde-runner", "varde_data.backends")
    assert "varde-runner imports varde_data.backends" in backend_import_violations(
        workspace
    )


def test_dependency_table_covers_every_workspace_project() -> None:
    workspace_modules = {
        package.relative_to(ROOT).parts[0] for package in _project_paths(ROOT).values()
    }
    assert workspace_modules == set(load_layers(ROOT / "layers.toml"))


def test_layer_distribution_names_match_projects(workspace: Path) -> None:
    layers_path = workspace / "layers.toml"
    original = layers_path.read_text()
    _write_text(
        layers_path, original.replace('dist = "varde-toz"', 'dist = "wrong-name"')
    )
    assert (
        "layers.toml distribution for toz does not match pyproject.toml"
        in violations(workspace)
    )


def test_undeclared_import_reports_package_and_dependency(workspace: Path) -> None:
    path = _project_paths(workspace)["varde-toz"] / "pyproject.toml"
    original = path.read_text()
    metadata = tomllib.loads(original)
    dependencies = metadata["project"]["dependencies"]
    updated = [item for item in dependencies if Requirement(item).name != "varde-core"]
    assert len(updated) < len(dependencies)
    import re

    replacement = "dependencies = [" + ", ".join(f'"{item}"' for item in updated) + "]"
    text, count = re.subn(r"dependencies = \[[^\]]*\]", replacement, original, count=1)
    assert count == 1
    _write_text(path, text)

    assert "varde-toz imports undeclared dependency varde-core" in violations(workspace)


def test_unused_declaration_reports_package_and_dependency(workspace: Path) -> None:
    package = _project_paths(workspace)["varde-toz"]
    for source in (package / "src").rglob("*.py"):
        source.unlink()
    assert "varde-toz declares unused dependency varde-core" in violations(workspace)


def test_module_plugin_dependency_is_not_unused(workspace: Path) -> None:
    _add_dependency(workspace, "varde", "varde-visualize")
    assert "varde declares unused dependency varde-visualize" not in violations(
        workspace
    )


def test_every_provider_is_a_varde_runtime_dependency() -> None:
    projects = _project_paths(ROOT)
    metadata = tomllib.loads((projects[APP] / "pyproject.toml").read_text())
    assert (_provider_projects(ROOT) - {APP}) <= _runtime_dependencies(metadata)


def test_source_import_must_be_a_runtime_dependency(workspace: Path) -> None:
    path = _project_paths(workspace)["varde"] / "pyproject.toml"
    original = path.read_text()
    metadata = tomllib.loads(original)
    dependencies = metadata["project"]["dependencies"]
    updated = [
        item for item in dependencies if Requirement(item).name != "varde-visualize"
    ]
    assert len(updated) < len(dependencies)
    updated, count = original.replace('"varde-visualize", ', "", 1), 1
    assert count == 1 and updated != original
    updated = updated.replace(
        '"pex==2.103.4"]', '"pex==2.103.4", "varde-visualize"]', 1
    )
    assert updated != original
    _write_text(path, updated)
    _add_import(workspace, "varde", "varde_visualize")
    assert "varde imports undeclared dependency varde-visualize" in violations(
        workspace
    )


def test_unused_runtime_dependency_used_only_by_tests_is_rejected(
    workspace: Path,
) -> None:
    package = _project_paths(workspace)["varde-toz"]
    for source in (package / "src").rglob("*.py"):
        source.unlink()
    path = package / "pyproject.toml"
    _write_text(
        path, path.read_text() + '\n[dependency-groups]\ndev = ["varde-core"]\n'
    )
    tests = package / "tests"
    tests.mkdir(exist_ok=True)
    _write_text(tests / "test_fake_import.py", "import varde_core\n")
    errors = violations(workspace)
    assert "varde-toz declares unused dependency varde-core" in errors


def test_module_root_and_skills_only_projects_report_named_violations(
    workspace: Path,
) -> None:
    module = workspace / "m"
    (module / "src").mkdir(parents=True)
    package = _project_paths(workspace)["varde-toz"]
    shutil.move(str(package / "pyproject.toml"), module / "pyproject.toml")
    shutil.move(str(package / "src" / "varde_toz"), module / "src" / "m_pkg")
    shutil.rmtree(package)
    layers_path = workspace / "layers.toml"
    _write_text(
        layers_path, layers_path.read_text().replace("[module.toz]", "[module.m]")
    )
    _write_text(
        module / "pyproject.toml", '[project]\nname="varde-toz"\ndependencies=[]\n'
    )
    dev = workspace / "dev"
    (dev / "src" / "varde_dev" / "skills" / "varde-explore").mkdir(parents=True)
    _write_text(dev / "src" / "varde_dev" / "__init__.py", "")
    _write_text(
        dev / "src" / "varde_dev" / "skills" / "varde-explore" / "SKILL.md",
        "# Explore\n",
    )
    _write_text(
        dev / "pyproject.toml", '[project]\nname="varde-dev"\ndependencies=[]\n'
    )

    module_init = module / "src" / "m_pkg" / "__init__.py"
    _write_text(module_init, "import varde_core\n")
    errors = violations(workspace)
    assert "varde-toz imports undeclared dependency varde-core" in errors

    _write_text(module_init, "")
    _write_text(
        dev / "pyproject.toml",
        '[project]\nname="varde-dev"\ndependencies=["varde-core"]\n',
    )
    errors = violations(workspace)
    assert "varde-dev declares unused dependency varde-core" in errors

    _write_text(module_init, "import varde_code\n")
    module_metadata = module / "pyproject.toml"
    _write_text(
        module_metadata,
        module_metadata.read_text().replace(
            "dependencies = [", 'dependencies = ["varde-code", ', 1
        ),
    )
    errors = violations(workspace)
    assert "varde-toz must not depend on varde-code" in errors


def test_friction_store_filenames_are_confined_to_data(workspace: Path) -> None:
    for package in ("varde-learn", APP):
        source = _project_paths(workspace)[package] / "src"
        for path in source.rglob("*.py"):
            contents = path.read_text(encoding="utf-8")
            assert "friction.jsonl" not in contents, path
            assert "learn.db" not in contents, path
