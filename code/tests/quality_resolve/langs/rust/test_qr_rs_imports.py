from varde_code.quality_resolve import edges_for_file, prepare
from varde_code.quality_resolve.langs.rust import import_bindings, import_targets


def test_crate_path_maps_to_rust_module_files():
    files = (
        "crates/engine/src/lib.rs",
        "crates/engine/src/format.rs",
        "crates/engine/src/format/mod.rs",
        "crates/engine/src/format/pretty.rs",
        "crates/other/src/lib.rs",
    )
    facts = {path: {} for path in files}

    assert import_targets(
        {"line": 2, "module": "crate::format::pretty::*"},
        "crates/engine/src/lib.rs",
        files,
        facts,
    ) == ["crates/engine/src/format/pretty.rs"]


def test_self_and_super_paths_are_relative_to_importing_module():
    files = (
        "crates/engine/src/lib.rs",
        "crates/engine/src/format/mod.rs",
        "crates/engine/src/format/render.rs",
        "crates/engine/src/format/types.rs",
        "crates/engine/src/types.rs",
    )
    facts = {path: {} for path in files}

    assert import_targets(
        {"line": 1, "module": "self::types::*"},
        "crates/engine/src/format/mod.rs",
        files,
        facts,
    ) == ["crates/engine/src/format/types.rs"]
    assert import_targets(
        {"line": 2, "module": "super::types::*"},
        "crates/engine/src/format/mod.rs",
        files,
        facts,
    ) == ["crates/engine/src/types.rs"]


def test_repeated_super_paths_walk_up_each_module():
    files = (
        "crates/engine/src/lib.rs",
        "crates/engine/src/a/mod.rs",
        "crates/engine/src/a/b/mod.rs",
        "crates/engine/src/a/b/c/mod.rs",
        "crates/engine/src/a/c.rs",
    )
    assert import_targets(
        {"module": "super::super::c::f"},
        "crates/engine/src/a/b/c/mod.rs",
        files,
        {},
    ) == ["crates/engine/src/a/c.rs"]


def test_external_crate_leaf_is_not_bound_through_shorter_prefix():
    files = ("core/src/lib.rs", "app/src/main.rs")
    context = {"core/src/lib.rs": {"functions": [{"name": "max"}]}}
    assert (
        import_bindings(
            {"module": "core::cmp::max", "text": "use core::cmp::max;"},
            "app/src/main.rs",
            files,
            context,
        )
        == []
    )


def test_workspace_crate_name_maps_to_matching_crate_root():
    files = (
        "crates/rayon-core/src/lib.rs",
        "crates/rayon-core/src/registry.rs",
        "crates/rayon/src/lib.rs",
        "crates/rayon/src/prelude.rs",
        "app/src/main.rs",
    )
    facts = {path: {} for path in files}

    assert import_targets(
        {"line": 4, "module": "rayon::prelude::*"},
        "app/src/main.rs",
        files,
        facts,
    ) == ["crates/rayon/src/prelude.rs"]


def test_associated_function_resolves_when_use_binding_is_present():
    facts = {
        "crates/engine/src/main.rs": {
            "imports": [
                {
                    "line": 1,
                    "module": "crate::format::Format",
                    "text": "use crate::format::Format;",
                }
            ],
            "call_sites": [
                {
                    "caller": "run",
                    "name": "new",
                    "receiver_text": "Format",
                    "arity": 0,
                }
            ],
        },
        "crates/engine/src/format.rs": {
            "types": [{"id": "Format", "name": "Format", "kind": "struct"}],
            "functions": [
                {"id": "Format::new", "name": "new", "owner": "Format", "params": 0}
            ],
        },
    }

    assert import_bindings(
        facts["crates/engine/src/main.rs"]["imports"][0],
        "crates/engine/src/main.rs",
        tuple(facts),
        facts,
    ) == [
        {
            "path": "crates/engine/src/format.rs",
            "names": ["Format"],
            "binding": "Format",
        }
    ]


def test_use_function_import_binds_only_the_named_function():
    files = ("crates/engine/src/lib.rs", "crates/engine/src/a.rs")
    facts = {
        "crates/engine/src/lib.rs": {
            "imports": [
                {"line": 1, "module": "crate::a::f", "text": "use crate::a::f;"}
            ],
            "call_sites": [{"caller": "run", "name": "f", "arity": 0}],
        },
        "crates/engine/src/a.rs": {
            "functions": [{"id": "a::f", "name": "f", "params": 0}]
        },
    }

    assert import_bindings(
        facts["crates/engine/src/lib.rs"]["imports"][0],
        "crates/engine/src/lib.rs",
        files,
        facts,
    ) == [{"path": "crates/engine/src/a.rs", "names": ["f"], "binding": None}]
    edge = edges_for_file(prepare(facts, facts), "crates/engine/src/lib.rs")[0]
    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "resolved",
        "imported",
        "a::f",
    )


def test_use_module_and_mod_declaration_create_receiver_bindings():
    files = ("crates/engine/src/lib.rs", "crates/engine/src/a.rs")
    for module, text in (("crate::a", "use crate::a;"), ("mod a", "mod a;")):
        spec = {"line": 1, "module": module, "text": text}
        facts = {
            "crates/engine/src/lib.rs": {
                "imports": [spec],
                "call_sites": [
                    {
                        "caller": "run",
                        "name": "f",
                        "receiver_text": "a",
                        "arity": 0,
                    }
                ],
            },
            "crates/engine/src/a.rs": {
                "functions": [{"id": "a::f", "name": "f", "params": 0}]
            },
        }

        assert import_bindings(spec, "crates/engine/src/lib.rs", files, facts) == [
            {"path": "crates/engine/src/a.rs", "names": [], "binding": "a"}
        ]
        edge = edges_for_file(prepare(facts, facts), "crates/engine/src/lib.rs")[0]
        assert (edge["kind"], edge["pass"], edge["callee"]) == (
            "resolved",
            "receiver",
            "a::f",
        )


def test_use_type_binding_resolves_associated_function():
    files = ("crates/engine/src/lib.rs", "crates/engine/src/a.rs")
    facts = {
        "crates/engine/src/lib.rs": {
            "imports": [
                {
                    "line": 1,
                    "module": "crate::a::Format",
                    "text": "use crate::a::Format;",
                }
            ],
            "call_sites": [
                {
                    "caller": "run",
                    "name": "new",
                    "receiver_text": "Format",
                    "arity": 0,
                }
            ],
        },
        "crates/engine/src/a.rs": {
            "types": [{"id": "Format", "name": "Format", "kind": "struct"}],
            "functions": [
                {
                    "id": "Format::new",
                    "name": "new",
                    "owner": "Format",
                    "params": 0,
                }
            ],
        },
    }

    assert import_bindings(
        facts["crates/engine/src/lib.rs"]["imports"][0],
        "crates/engine/src/lib.rs",
        files,
        facts,
    ) == [
        {
            "path": "crates/engine/src/a.rs",
            "names": ["Format"],
            "binding": "Format",
        }
    ]


def test_glob_import_exposes_functions_from_target_module():
    files = ("crates/engine/src/lib.rs", "crates/engine/src/a.rs")
    facts = {
        "crates/engine/src/lib.rs": {
            "imports": [
                {"line": 1, "module": "crate::a::*", "text": "use crate::a::*;"}
            ],
            "call_sites": [{"caller": "run", "name": "f", "arity": 0}],
        },
        "crates/engine/src/a.rs": {
            "functions": [{"id": "a::f", "name": "f", "params": 0}]
        },
    }

    assert import_bindings(
        facts["crates/engine/src/lib.rs"]["imports"][0],
        "crates/engine/src/lib.rs",
        files,
        facts,
    ) == [{"path": "crates/engine/src/a.rs", "names": "*", "binding": None}]
    edge = edges_for_file(prepare(facts, facts), "crates/engine/src/lib.rs")[0]
    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "resolved",
        "imported",
        "a::f",
    )


def test_grouped_use_binds_function_type_and_glob_items():
    files = (
        "crates/engine/src/lib.rs",
        "crates/engine/src/a.rs",
        "crates/engine/src/a/nested.rs",
    )
    facts = {
        "crates/engine/src/lib.rs": {
            "imports": [
                {
                    "line": 1,
                    "module": "crate::a",
                    "text": "use crate::a::{f, Type, nested::*};",
                }
            ],
            "call_sites": [
                {"caller": "run", "name": "f", "arity": 0},
                {
                    "caller": "run",
                    "name": "new",
                    "receiver_text": "Type",
                    "arity": 0,
                },
            ],
        },
        "crates/engine/src/a.rs": {
            "types": [{"id": "Type", "name": "Type", "kind": "struct"}],
            "functions": [
                {"id": "a::f", "name": "f", "params": 0},
                {
                    "id": "Type::new",
                    "name": "new",
                    "owner": "Type",
                    "params": 0,
                },
            ],
        },
        "crates/engine/src/a/nested.rs": {
            "functions": [{"id": "a::nested::g", "name": "g", "params": 0}]
        },
    }

    bindings = import_bindings(
        facts["crates/engine/src/lib.rs"]["imports"][0],
        "crates/engine/src/lib.rs",
        files,
        facts,
    )
    assert bindings == [
        {"path": "crates/engine/src/a.rs", "names": ["Type"], "binding": "Type"},
        {"path": "crates/engine/src/a.rs", "names": ["f"], "binding": None},
        {"path": "crates/engine/src/a/nested.rs", "names": "*", "binding": None},
    ]
    edges = edges_for_file(prepare(facts, facts), "crates/engine/src/lib.rs")
    assert [(edge["kind"], edge["pass"], edge["callee"]) for edge in edges] == [
        ("resolved", "imported", "a::f"),
        ("resolved", "imported", "Type::new"),
    ]


def test_pub_use_reexports_the_named_item_and_unknown_syntax_binds_nothing():
    files = ("crates/engine/src/lib.rs", "crates/engine/src/a.rs")
    context = {
        "crates/engine/src/lib.rs": {},
        "crates/engine/src/a.rs": {
            "functions": [{"id": "a::f", "name": "f", "params": 0}]
        },
    }

    assert import_bindings(
        {
            "line": 1,
            "module": "crate::a",
            "text": "pub use crate::a::f;",
        },
        "crates/engine/src/lib.rs",
        files,
        context,
    ) == [{"path": "crates/engine/src/a.rs", "names": ["f"], "binding": None}]
    assert import_bindings(
        {
            "line": 1,
            "module": "crate::a",
            "text": "use crate::a::{f, invalid!()};",
        },
        "crates/engine/src/lib.rs",
        files,
        context,
    ) == [{"path": "crates/engine/src/a.rs", "names": [], "binding": None}]


def test_use_function_alias_maps_visible_name_to_source_name():
    files = ("crates/engine/src/lib.rs", "crates/engine/src/a.rs")
    facts = {
        "crates/engine/src/lib.rs": {
            "imports": [
                {
                    "line": 1,
                    "module": "crate::a::f",
                    "text": "use crate::a::f as g;",
                }
            ],
            "call_sites": [{"caller": "run", "name": "g", "arity": 0}],
        },
        "crates/engine/src/a.rs": {
            "functions": [{"id": "a::f", "name": "f", "params": 0}]
        },
    }

    assert import_bindings(
        facts["crates/engine/src/lib.rs"]["imports"][0],
        "crates/engine/src/lib.rs",
        files,
        facts,
    ) == [
        {
            "path": "crates/engine/src/a.rs",
            "names": [],
            "aliases": {"g": "f"},
            "binding": None,
        }
    ]
    edge = edges_for_file(prepare(facts, facts), "crates/engine/src/lib.rs")[0]
    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "resolved",
        "imported",
        "a::f",
    )
