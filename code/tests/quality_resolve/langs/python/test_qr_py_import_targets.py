from varde_code.quality_resolve import edges_for_file, prepare
from varde_code.quality_resolve.langs.python import import_bindings, import_targets


def test_from_import_tracks_named_imports_and_aliases():
    paths = ("pkg/lib.py", "pkg/main.py")
    assert import_bindings(
        {
            "module": "lib",
            "line": 1,
            "text": "from lib import work as w, other",
        },
        "pkg/main.py",
        paths,
        {},
    ) == [
        {
            "path": "pkg/lib.py",
            "names": ["other"],
            "aliases": {"w": "work"},
            "binding": None,
        }
    ]


def test_python_alias_binding_resolves_imported_call():
    facts = {
        "src/main.py": {
            "imports": [
                {
                    "module": "lib",
                    "line": 1,
                    "text": "from lib import work as w",
                }
            ],
            "call_sites": [{"name": "w", "receiver_text": None}],
        },
        "src/lib.py": {"functions": [{"id": "lib-work", "name": "work"}]},
    }
    edge = edges_for_file(prepare(facts, facts), "src/main.py")[0]
    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "resolved",
        "imported",
        "lib-work",
    )


def test_module_import_binds_module_name_and_alias():
    paths = ("pkg/a.py", "pkg/main.py")
    assert import_bindings(
        {"module": "a", "text": "import a as b", "line": 1},
        "pkg/main.py",
        paths,
        {},
    ) == [{"path": "pkg/a.py", "names": [], "binding": "b"}]


def test_module_import_binds_unaliased_name():
    paths = ("pkg/a.py", "pkg/main.py")
    assert import_bindings(
        {"module": "a", "text": "import a", "line": 1},
        "pkg/main.py",
        paths,
        {},
    ) == [{"path": "pkg/a.py", "names": [], "binding": "a"}]


def test_dotted_import_without_alias_binds_dotted_module_and_package():
    paths = ("a/__init__.py", "a/b.py", "main.py")
    assert import_bindings(
        {"module": "a/b", "text": "import a.b", "line": 1}, "main.py", paths, {}
    ) == [
        {"path": "a/b.py", "names": [], "binding": "a.b"},
        {"path": "a/__init__.py", "names": [], "binding": "a"},
    ]


def test_dotted_import_alias_binds_only_the_alias():
    paths = ("pkg/__init__.py", "pkg/helper.py", "main.py")
    assert import_bindings(
        {"module": "pkg/helper", "text": "import pkg.helper as h", "line": 1},
        "main.py",
        paths,
        {},
    ) == [{"path": "pkg/helper.py", "names": [], "binding": "h"}]


def test_dotted_import_without_package_does_not_bind_child_as_parent():
    paths = ("a/b.py", "main.py")
    assert (
        import_bindings(
            {"module": "a/b", "text": "import a.b", "line": 1}, "main.py", paths, {}
        )
        == []
    )


def test_absolute_import_with_duplicate_sibling_basename_is_ambiguous():
    paths = ("a/lib.py", "b/lib.py", "a/main.py")
    assert import_targets({"module": "lib"}, "a/main.py", paths, {}) == []


def test_conditional_duplicate_imports_remain_ambiguous():
    facts = {
        "main.py": {
            "imports": [
                {"module": "a", "line": 1, "text": "from a import work"},
                {"module": "b", "line": 3, "text": "from b import work"},
            ],
            "call_sites": [{"name": "work", "receiver_text": None}],
        },
        "a.py": {"functions": [{"id": "a-work", "name": "work"}]},
        "b.py": {"functions": [{"id": "b-work", "name": "work"}]},
    }
    edge = edges_for_file(prepare(facts, facts), "main.py")[0]
    assert edge["kind"] == "ambiguous"


def test_repeated_alias_imports_remain_ambiguous():
    facts = {
        "main.py": {
            "imports": [
                {"module": "x/m", "line": 1, "text": "import x.m as m"},
                {"module": "y/m", "line": 2, "text": "import y.m as m"},
            ],
            "call_sites": [{"name": "work", "receiver_text": "m"}],
        },
        "x/m.py": {"functions": [{"id": "x-work", "name": "work"}]},
        "y/m.py": {"functions": [{"id": "y-work", "name": "work"}]},
    }
    edge = edges_for_file(prepare(facts, facts), "main.py")[0]
    assert edge["kind"] == "ambiguous"


def test_from_import_binds_submodule_for_absolute_and_relative_imports():
    paths = ("pkg/__init__.py", "pkg/sub.py", "pkg/main.py")
    for module, text in (("pkg", "from pkg import sub"), (".", "from . import sub")):
        assert import_bindings(
            {"module": module, "text": text, "line": 1}, "pkg/main.py", paths, {}
        ) == [{"path": "pkg/sub.py", "names": [], "binding": "sub"}]


def test_relative_from_import_resolves_module_and_name():
    paths = ("pkg/__init__.py", "pkg/a.py", "pkg/main.py")
    assert import_bindings(
        {"module": "./a", "text": "from .a import work", "line": 1},
        "pkg/main.py",
        paths,
        {},
    ) == [{"path": "pkg/a.py", "names": ["work"], "aliases": {}, "binding": None}]


def test_relative_star_import_binds_all_functions_from_package_init():
    paths = ("pkg/__init__.py", "pkg/main.py")
    context = {
        "pkg/__init__.py": {
            "functions": [
                {"name": "public"},
                {"name": "_private"},
                {"name": "method", "owner": "Thing"},
            ]
        }
    }
    assert import_bindings(
        {"module": ".", "text": "from . import *", "line": 1},
        "pkg/main.py",
        paths,
        context,
    ) == [
        {
            "path": "pkg/__init__.py",
            "names": ["public"],
            "aliases": {},
            "binding": None,
        }
    ]


def test_relative_import_from_package_binds_submodule_receiver():
    paths = ("pkg/main.py", "pkg/x.py")
    assert import_bindings(
        {"module": "./x", "text": "from . import x", "line": 1},
        "pkg/main.py",
        paths,
        {},
    ) == [{"path": "pkg/x.py", "names": [], "binding": "x"}]


def test_star_import_respects_explicit_all_names():
    paths = ("pkg/lib.py", "pkg/main.py")
    context = {
        "pkg/lib.py": {
            "exported_names": [[None, "public"]],
            "functions": [{"name": "public"}, {"name": "private"}],
        }
    }
    assert import_bindings(
        {"module": "lib", "text": "from lib import *", "line": 1},
        "pkg/main.py",
        paths,
        context,
    ) == [{"path": "pkg/lib.py", "names": ["public"], "aliases": {}, "binding": None}]


def test_star_import_without_export_facts_uses_public_module_functions():
    paths = ("pkg/lib.py", "pkg/main.py")
    context = {
        "pkg/lib.py": {
            "functions": [
                {"name": "public"},
                {"name": "_private"},
                {"name": "method", "owner": "Thing"},
            ]
        }
    }
    assert import_bindings(
        {"module": "lib", "text": "from lib import *", "line": 1},
        "pkg/main.py",
        paths,
        context,
    ) == [
        {
            "path": "pkg/lib.py",
            "names": ["public"],
            "aliases": {},
            "binding": None,
        }
    ]


def test_package_import_can_bind_reexported_name_from_init():
    paths = ("pkg/__init__.py", "pkg/main.py")
    assert import_bindings(
        {"module": "pkg", "text": "from pkg import work", "line": 1},
        "pkg/main.py",
        paths,
        {},
    ) == [
        {"path": "pkg/__init__.py", "names": ["work"], "aliases": {}, "binding": None}
    ]


def test_relative_import_path_resolves_from_importer_directory():
    paths = ("pkg/__init__.py", "pkg/api.py", "pkg/sub/main.py")
    assert import_targets(
        {"module": "../api", "line": 1}, "pkg/sub/main.py", paths, {}
    ) == ["pkg/api.py"]


def test_ambiguous_module_remains_unresolved():
    paths = ("pkg/api.py", "other/api.py")
    assert import_targets({"module": "api"}, "main.py", paths, {}) == []


def test_package_module_resolves_to_init():
    paths = ("pkg/__init__.py", "pkg/api.py")
    assert import_targets({"module": "pkg"}, "main.py", paths, {}) == [
        "pkg/__init__.py"
    ]


def test_top_level_module_resolves_from_importer_ancestor():
    paths = ("app/main.py", "app/lib.py")
    assert import_targets({"line": 1, "module": "lib"}, "app/main.py", paths, {}) == [
        "app/lib.py"
    ]
