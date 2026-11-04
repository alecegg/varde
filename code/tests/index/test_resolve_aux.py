from types import SimpleNamespace

from varde_code.index.resolve.aux import (
    Edge,
    build_nodes,
    compute_fan_metrics,
    detect_clone_bands,
    detect_communities,
    resolve_python_module,
    resolve_rust_module,
)
from varde_code.model import EntityKind


def test_graph_metrics_and_communities_are_deterministic():
    files = ["a.py", "b.py", "c.py"]
    nodes = build_nodes(files)
    edges = [Edge(from_file=0, to_file=1), Edge(from_file=1, to_file=0)]

    compute_fan_metrics(nodes, edges, [])
    communities = detect_communities(nodes, edges, [])

    assert [(node.fan_in, node.fan_out) for node in nodes] == [(1, 1), (1, 1), (0, 0)]
    assert [group.members for group in communities] == [["a.py", "b.py"], ["c.py"]]
    assert [node.community_id for node in nodes] == [0, 0, 1]


def test_clone_bands_only_include_functions_with_shared_band_hashes():
    entities: list[object] = [
        SimpleNamespace(
            kind=EntityKind.FUNCTION, name="one", file_id=0, body_minhash=[4, 8, 12, 16]
        ),
        SimpleNamespace(
            kind=EntityKind.FUNCTION,
            name="two",
            file_id=1,
            body_minhash=[4, 8, 99, 100],
        ),
        SimpleNamespace(
            kind=EntityKind.CLASS,
            name="not-a-function",
            file_id=2,
            body_minhash=[4, 8, 12, 16],
        ),
    ]

    assert [band.members for band in detect_clone_bands(entities)] == [[0, 1], [0, 1]]


def test_python_module_resolution_requires_unique_package_and_module():
    files = [
        "src/pkg/__init__.py",
        "src/pkg/child.py",
        "src/other/__init__.py",
        "src/other/child.py",
    ]

    assert resolve_python_module("pkg/child", "src/main.py", files) == 1
    assert resolve_python_module("missing/child", "src/main.py", files) is None
    assert resolve_python_module("child", "src/main.py", files) is None


def test_rust_module_declarations_and_crate_paths_follow_module_tree(tmp_path):
    root = tmp_path / "src"
    files = [
        str(root / "lib.rs"),
        str(root / "foo.rs"),
        str(root / "foo" / "bar.rs"),
    ]

    assert resolve_rust_module("mod foo", files[0], files) == 1
    assert resolve_rust_module("crate::foo::bar::Thing", files[0], files) == 2
    assert resolve_rust_module("super::Thing", files[2], files) == 1


def test_empty_graph_yields_stable_singleton_communities():
    nodes = build_nodes(["z.py", "a.py"])

    communities = detect_communities(nodes, [], [])

    assert [group.members for group in communities] == [["z.py"], ["a.py"]]
    assert [node.community_id for node in nodes] == [0, 1]
