"""The quality pass keeps its two-step adapter to the deep resolver."""

from varde_code.quality_pass import resolve_hook


def test_hook_is_the_deep_resolver_with_constructor_edges_enabled():
    facts = {
        "src/A.java": {
            "contract": "facts-2",
            "path": "src/A.java",
            "language": "java",
            "package": "src",
            "functions": [{"id": "src/A.java::A.run#1", "name": "run", "owner": "A"}],
            "types": [{"id": "src/A.java::A", "name": "A", "kind": "class"}],
            "imports": [],
            "call_sites": [
                {
                    "caller": "src/A.java::A.run#1",
                    "name": "B",
                    "receiver": None,
                    "receiver_text": None,
                    "arity": 0,
                    "line": 3,
                    "kind": "new",
                }
            ],
        },
        "src/B.java": {
            "contract": "facts-2",
            "path": "src/B.java",
            "language": "java",
            "package": "src",
            "functions": [
                {"id": "src/B.java::B.<init>#1", "name": "<init>", "owner": "B"}
            ],
            "types": [{"id": "src/B.java::B", "name": "B", "kind": "class"}],
            "imports": [],
            "call_sites": [],
        },
    }
    paths = list(facts)
    hook_context = resolve_hook.prepare(paths, facts)

    assert resolve_hook.edges_for_file(hook_context, "src/A.java") == [
        {
            "caller": "src/A.java::A.run#1",
            "site_line": 3,
            "callee": "src/B.java::B.<init>#1",
            "kind": "resolved",
            "pass": "namespace",
        }
    ]
    assert resolve_hook.digest_for_file(hook_context, "src/A.java")
    assert (
        resolve_hook.coverage(resolve_hook.edges_for_file(hook_context, "src/A.java"))[
            "resolved"
        ]
        == 1
    )
    assert resolve_hook.resolver_version() == resolve_hook.RESOLVER_VERSION


def test_hook_resolves_same_package_java_constructor():
    facts = {
        "src/A.java": {
            "contract": "facts-2",
            "path": "src/A.java",
            "language": "java",
            "package": "demo",
            "functions": [{"id": "A.run#1", "name": "run", "owner": "A"}],
            "types": [{"id": "A", "name": "A", "kind": "class"}],
            "imports": [],
            "call_sites": [
                {
                    "caller": "A.run#1",
                    "name": "B",
                    "receiver": None,
                    "receiver_text": None,
                    "arity": 0,
                    "line": 3,
                    "kind": "new",
                }
            ],
        },
        "src/B.java": {
            "contract": "facts-2",
            "path": "src/B.java",
            "language": "java",
            "package": "demo",
            "functions": [
                {"id": "src/B.java::B.<init>#1", "name": "<init>", "owner": "B"}
            ],
            "types": [{"id": "B", "name": "B", "kind": "class"}],
            "imports": [],
            "call_sites": [],
        },
    }
    edges = resolve_hook.edges_for_file(
        resolve_hook.prepare(list(facts), facts), "src/A.java"
    )
    assert edges == [
        {
            "caller": "A.run#1",
            "site_line": 3,
            "callee": "src/B.java::B.<init>#1",
            "kind": "resolved",
            "pass": "namespace",
        }
    ]


def test_hook_preserves_ambiguous_local_calls():
    facts = {
        "main.py": {
            "contract": "facts-2",
            "path": "main.py",
            "language": "python",
            "functions": [
                {"id": "main.py::entry#1", "name": "entry", "params": 0},
                {"id": "main.py::compute#1", "name": "compute", "params": 0},
                {"id": "main.py::compute#2", "name": "compute", "params": 0},
            ],
            "types": [],
            "imports": [],
            "call_sites": [
                {
                    "caller": "main.py::entry#1",
                    "name": "compute",
                    "receiver": None,
                    "receiver_text": None,
                    "arity": 0,
                    "line": 2,
                    "kind": "call",
                }
            ],
        },
    }
    edges = resolve_hook.edges_for_file(
        resolve_hook.prepare(list(facts), facts), "main.py"
    )
    assert edges[0]["kind"] == "ambiguous"


def test_hook_resolves_python_self_method_call():
    facts = {
        "main.py": {
            "contract": "facts-2",
            "path": "main.py",
            "language": "python",
            "functions": [
                {
                    "id": "main.py::K.run#1",
                    "name": "run",
                    "owner": "K",
                    "params": 1,
                },
                {
                    "id": "main.py::K.m#1",
                    "name": "m",
                    "owner": "K",
                    "params": 1,
                },
            ],
            "types": [{"id": "main.py::K", "name": "K", "kind": "class"}],
            "imports": [],
            "call_sites": [
                {
                    "caller": "main.py::K.run#1",
                    "name": "m",
                    "receiver": "self",
                    "receiver_text": "self",
                    "arity": 0,
                    "line": 3,
                    "kind": "call",
                }
            ],
        }
    }
    edges = resolve_hook.edges_for_file(
        resolve_hook.prepare(list(facts), facts), "main.py"
    )
    assert edges == [
        {
            "caller": "main.py::K.run#1",
            "site_line": 3,
            "callee": "main.py::K.m#1",
            "kind": "resolved",
            "pass": "receiver",
        }
    ]


def test_resolver_version_changes_with_resolver_source(monkeypatch, tmp_path):
    package = tmp_path / "quality_resolve"
    package.mkdir()
    source = package / "source.py"
    source.write_text("one", encoding="utf-8")
    monkeypatch.setattr(
        resolve_hook.quality_resolve, "__file__", str(package / "__init__.py")
    )
    first = resolve_hook._resolver_version()
    source.write_text("two", encoding="utf-8")
    assert resolve_hook._resolver_version() != first
