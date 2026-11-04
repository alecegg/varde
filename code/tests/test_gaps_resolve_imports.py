from pathlib import Path
from typing import Any, cast

from varde_code.index.resolve import resolve


def resolve_graph(*args: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", resolve(*args))


def test_import_resolution_uses_path_suffix_and_package_indexes():
    files = [
        "src/app.ts",
        "src/features/users/index.ts",
        "vendor/users/index.ts",
        "src/shared/format.ts",
    ]
    entities = [
        {"kind": "import", "name": "features.users", "file_id": 0},
        {"kind": "import", "name": "shared.format", "file_id": 0},
    ]

    edges = resolve_graph(entities, [], files)["edges"]

    assert [edge["to"] for edge in edges] == [
        {"target": "file", "id": 1},
        {"target": "file", "id": 3},
    ]


def test_rust_imports_dispatch_to_module_tree_resolver(tmp_path: Path):
    root = tmp_path / "crate" / "src"
    files = [str(root / "lib.rs"), str(root / "foo.rs"), str(root / "foo" / "bar.rs")]
    entities = [
        {"kind": "import", "name": "mod foo", "file_id": 0},
        {"kind": "import", "name": "crate::foo::bar::Thing", "file_id": 0},
    ]

    edges = resolve_graph(entities, [], files)["edges"]

    assert [edge["to"] for edge in edges] == [
        {"target": "file", "id": 1},
        {"target": "file", "id": 2},
    ]


def test_rust_imports_resolve_path_dependency_crates(tmp_path: Path):
    app = tmp_path / "app"
    dep = tmp_path / "dependency"
    (app / "Cargo.toml").parent.mkdir(parents=True)
    (app / "Cargo.toml").write_text(
        '[package]\nname = "app"\nversion = "0.1.0"\n'
        '[dependencies]\nhelper_crate = { path = "../dependency" }\n'
    )
    (dep / "src" / "module").mkdir(parents=True)
    (dep / "Cargo.toml").write_text(
        '[package]\nname = "helper-crate"\nversion = "0.1.0"\n'
    )
    files = [
        str(app / "src" / "lib.rs"),
        str(dep / "src" / "lib.rs"),
        str(dep / "src" / "module.rs"),
    ]

    graph = resolve_graph(
        [{"kind": "import", "name": "helper_crate::module::Thing", "file_id": 0}],
        [],
        files,
    )

    assert graph["edges"][0]["to"] == {"target": "file", "id": 2}


def test_go_import_targets_every_file_in_an_internal_package(tmp_path: Path):
    root = tmp_path / "go-project"
    root.mkdir()
    (root / "go.mod").write_text("module example.com/project\n")
    files = [
        str(root / "go.mod"),
        str(root / "cmd" / "main.go"),
        str(root / "pkg" / "one.go"),
        str(root / "pkg" / "two.go"),
        str(root / "pkg" / "pkg_test.go"),
    ]
    entities = [{"kind": "import", "name": "example.com/project/pkg", "file_id": 1}]

    edges = resolve_graph(entities, [], files)["edges"]

    assert [edge["to"] for edge in edges] == [
        {"target": "file", "id": 2},
        {"target": "file", "id": 3},
    ]


def test_namespaced_module_imports_resolve_to_the_declaring_file():
    graph = resolve_graph(
        [
            {"kind": "import", "name": "MyApp.Repo", "file_id": 0},
            {"kind": "class", "name": "MyApp.Repo", "file_id": 1},
        ],
        [],
        ["lib/my_app/user.ex", "lib/my_app/repo.ex"],
    )

    assert graph["edges"][0]["to"] == {"target": "file", "id": 1}
