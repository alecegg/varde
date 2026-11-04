import posixpath
import re
import time
from pathlib import PurePosixPath

from varde_code.quality_pass.facts import extract_facts
from varde_code.quality_pass.pass_.extract import import_specs
from varde_code.quality_resolve import edges_for_file, prepare
from varde_code.quality_resolve.langs.cpp import (
    _header_paths,
    import_bindings,
    import_targets,
)


def test_include_resolves_relative_to_including_file():
    targets = import_targets(
        {"module": "detail/value.h", "text": '#include "detail/value.h"'},
        "src/widget.cc",
        ("src/detail/value.h", "src/widget.cc", "src/detail/value.cc"),
        {},
    )

    assert targets == ["src/detail/value.h"]


def test_include_resolves_under_an_include_root():
    targets = import_targets(
        {"module": "library/value.h", "text": '#include "library/value.h"'},
        "src/widget.cc",
        ("include/library/value.h", "src/widget.cc"),
        {},
    )

    assert targets == ["include/library/value.h"]


def test_root_relative_include_matches_exact_path_and_nested_candidates():
    targets = import_targets(
        {"text": '#include "util/coding.h"'},
        "db/version_set.cc",
        ("util/coding.h", "vendor/util/coding.h", "db/version_set.cc"),
        {},
    )

    assert targets == ["util/coding.h", "vendor/util/coding.h"]


def test_indexed_include_lookup_matches_naive_lookup():
    paths = (
        "src/main.cc",
        "src/local/value.h",
        "include/project/value.h",
        "vendor/project/value.h",
        "value.h",
        "src/other.cc",
    )
    specs = (
        {"text": '#include "local/value.h"'},
        {"text": '#include "project/value.h"'},
        {"text": "#include <project/value.h>"},
        {"text": "#include <value.h>"},
        {"text": '#include "missing.h"'},
    )
    for importer in ("src/main.cc", "root.cc"):
        for spec in specs:
            assert _header_paths(spec, importer, paths) == _naive_header_paths(
                spec, importer, paths
            )


def _naive_header_paths(spec, importer_path, file_set):
    statement = spec.get("text")
    if not isinstance(statement, str):
        return []
    match = re.fullmatch(
        r'^\s*#\s*include\s*(?:"([^"\n]+)"|<([^>\n]+)>)\s*$', statement
    )
    if match is None:
        return []
    include = (match.group(1) or match.group(2)).strip()
    headers = {
        path
        for path in file_set
        if PurePosixPath(path).suffix.lower()
        in {".h", ".hh", ".hpp", ".hxx", ".h++", ".inl", ".ipp", ".tcc"}
    }
    normalized = posixpath.normpath(include)
    relative = posixpath.normpath(
        posixpath.join(posixpath.dirname(importer_path), normalized)
    )
    if not relative.startswith("../") and relative != ".." and relative in headers:
        return [relative]
    if normalized.startswith("../") or (
        match.group(2) is not None and "/" not in normalized
    ):
        return []
    return sorted(
        path
        for path in headers
        if path == normalized or path.endswith("/" + normalized)
    )


def test_cpp_include_index_scales_to_4000_files_and_10_includes_each():
    files = tuple(
        [f"src/file_{index}.cc" for index in range(2000)]
        + [f"include/group_{index}/shared.h" for index in range(2000)]
    )
    specs = [{"text": f'#include "group_{index}/shared.h"'} for index in range(10)]
    start = time.perf_counter()
    for importer in files:
        for spec in specs:
            _header_paths(spec, importer, files)
    elapsed = time.perf_counter() - start
    assert elapsed < 20


def test_root_relative_include_matches_a_top_level_header():
    targets = import_targets(
        {"text": '#include "coding.h"'}, "db/version_set.cc", ("coding.h",), {}
    )

    assert targets == ["coding.h"]


def test_dot_prefixed_hidden_header_keeps_its_leading_dot():
    targets = import_targets(
        {"text": '#include ".hidden/value.h"'},
        "src/main.cc",
        (".hidden/value.h", "src/main.cc"),
        {},
    )

    assert targets == [".hidden/value.h"]


def test_angled_project_header_resolves_but_bare_system_header_stays_external():
    targets = import_targets(
        {"text": "#include <assimp/scene.h>"},
        "code/main.cc",
        ("include/assimp/scene.h",),
        {},
    )

    assert targets == ["include/assimp/scene.h"]
    assert (
        import_targets({"text": "#include <vector>"}, "code/main.cc", ("vector",), {})
        == []
    )


def test_include_binds_header_like_suffixes():
    for suffix in (".inl", ".ipp", ".tcc", ".h++"):
        assert import_targets(
            {"text": f'#include "detail/vector{suffix}"'},
            "src/main.cc",
            (f"include/detail/vector{suffix}",),
            {},
        ) == [f"include/detail/vector{suffix}"]


def test_relative_include_may_traverse_to_repository_include_root():
    targets = import_targets(
        {"module": "../../include/value.h", "text": '#include "../../include/value.h"'},
        "src/widgets/main.cc",
        ("include/value.h", "src/widgets/main.cc"),
        {},
    )

    assert targets == ["include/value.h"]


def test_ambiguous_include_paths_remain_candidates():
    targets = import_targets(
        {"module": "library/value.h", "text": '#include "library/value.h"'},
        "src/widget.cc",
        ("include/library/value.h", "vendor/library/value.h", "src/widget.cc"),
        {},
    )

    assert targets == ["include/library/value.h", "vendor/library/value.h"]


def test_system_include_without_a_project_header_has_no_target():
    targets = import_targets(
        {"module": "vector", "text": "#include <vector>"},
        "src/widget.cc",
        ("src/widget.cc",),
        {},
    )

    assert targets == []


def test_include_binds_every_function_in_header():
    bindings = import_bindings(
        {"line": 1, "module": "widget.h", "text": '#include "widget.h"'},
        "src/main.cc",
        ("src/main.cc", "src/widget.h"),
        {},
    )

    assert bindings == [{"path": "src/widget.h", "names": "*", "binding": None}]


def test_include_binds_declared_namespace_qualifiers():
    bindings = import_bindings(
        {"text": '#include "widget.h"'},
        "src/main.cc",
        ("src/widget.h",),
        {"src/widget.h": {"functions": [{"name": "build", "qualifier": "n"}]}},
    )

    assert bindings == [
        {"path": "src/widget.h", "names": "*", "binding": None},
        {"path": "src/widget.h", "names": "*", "binding": "n"},
    ]


def test_include_binds_paired_source_definitions():
    bindings = import_bindings(
        {"line": 1, "module": "widget.h", "text": '#include "widget.h"'},
        "src/main.cc",
        ("include/widget.h", "src/main.cc", "src/widget.cpp"),
        {"src/widget.cpp": {"functions": [{"name": "build"}]}},
    )

    assert bindings == [
        {"path": "include/widget.h", "names": "*", "binding": None},
        {"path": "src/widget.cpp", "names": "*", "binding": None},
    ]


def test_include_import_resolves_unqualified_header_function():
    facts = {
        "src/main.cc": {
            "imports": [
                {"line": 1, "module": "widget.h", "text": '#include "widget.h"'}
            ],
            "functions": [{"id": "main", "name": "main", "params": 0}],
            "call_sites": [{"caller": "main", "name": "build", "arity": 0}],
        },
        "src/widget.h": {
            "functions": [{"id": "build-inline", "name": "build", "params": 0}]
        },
    }

    edge = edges_for_file(prepare(facts, facts), "src/main.cc")[0]

    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "resolved",
        "imported",
        "build-inline",
    )


def test_include_import_resolves_paired_source_definition():
    facts = {
        "src/main.cc": {
            "imports": [
                {"line": 1, "module": "widget.h", "text": '#include "widget.h"'}
            ],
            "functions": [{"id": "main", "name": "main", "params": 0}],
            "call_sites": [{"caller": "main", "name": "build", "arity": 0}],
        },
        "include/widget.h": {"functions": []},
        "src/widget.cpp": {
            "functions": [{"id": "build-def", "name": "build", "params": 0}]
        },
    }

    edge = edges_for_file(prepare(facts, facts), "src/main.cc")[0]

    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "resolved",
        "imported",
        "build-def",
    )


def test_system_include_cannot_guess_a_project_header():
    facts = {
        "src/main.cc": {
            "imports": [{"line": 1, "module": "vector", "text": "#include <vector>"}],
            "call_sites": [{"name": "push", "receiver_text": "vector", "arity": 0}],
        },
        "src/vector.h": {
            "functions": [{"id": "project-push", "name": "push", "params": 0}]
        },
    }

    edge = edges_for_file(prepare(facts, facts), "src/main.cc")[0]

    assert edge["kind"] == "external"
    assert edge["callee"] is None


def test_receiver_variable_stays_opaque_even_when_header_declares_name():
    facts = {
        "src/main.cc": {
            "imports": [
                {"line": 1, "module": "stream.h", "text": '#include "stream.h"'}
            ],
            "call_sites": [{"name": "Read", "receiver_text": "stream", "arity": 1}],
        },
        "src/stream.h": {"functions": [{"id": "read", "name": "Read", "params": 1}]},
    }

    edge = edges_for_file(prepare(facts, facts), "src/main.cc")[0]

    assert (edge["kind"], edge["callee"]) == ("opaque", None)


def test_dotted_namespace_type_receiver_resolves_qualified_method():
    header = "namespace ns { class Foo { public: static void g() {} }; }\n"
    source = '#include "foo.h"\nvoid caller() { ns::Foo::g(); }\n'
    header_facts = extract_facts(header, "cpp", "src/foo.h")
    source_facts = extract_facts(source, "cpp", "src/main.cc")
    source_facts["imports"] = import_specs("src/main.cc", source, "cpp")
    facts = {"src/foo.h": header_facts, "src/main.cc": source_facts}

    edge = edges_for_file(prepare(facts, facts), "src/main.cc")[0]

    assert source_facts["call_sites"][0]["receiver_text"] == "ns.Foo"
    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "resolved",
        "receiver",
        "src/foo.h::Foo.g#1",
    )


def test_new_expression_resolves_included_cpp_constructor():
    header = "class B { public: B(int value) {} };\n"
    source = '#include "widget.h"\nvoid caller() { new B(1); }\n'
    header_facts = extract_facts(header, "cpp", "src/widget.h")
    source_facts = extract_facts(source, "cpp", "src/main.cc")
    source_facts["imports"] = import_specs("src/main.cc", source, "cpp")
    facts = {"src/widget.h": header_facts, "src/main.cc": source_facts}

    edge = edges_for_file(prepare(facts, facts), "src/main.cc")[0]

    assert source_facts["call_sites"][0]["kind"] == "new"
    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "resolved",
        "local",
        "src/widget.h::B.B#1",
    )
