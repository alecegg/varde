from varde_code.quality_resolve import digest_for_file, edges_for_file, prepare


def _facts(receiver_text, name, imports=None):
    return {
        "main.py": {
            "imports": imports or [],
            "functions": [{"id": "caller", "name": "caller", "params": 0}],
            "call_sites": [
                {
                    "caller": "caller",
                    "name": name,
                    "receiver_text": receiver_text,
                    "arity": 0,
                }
            ],
        }
    }


def test_receiver_calls_never_fall_back_to_bare_imported_names():
    facts = _facts("stream", "f", [{"module": "lib", "name": "f"}])
    facts["lib.py"] = {"functions": [{"id": "f", "name": "f", "params": 0}]}
    assert edges_for_file(prepare(list(facts), facts), "main.py")[0]["kind"] == "opaque"


def test_module_binding_resolves_only_matching_receiver():
    facts = _facts("mod", "f", [{"module": "lib", "alias": "mod"}])
    facts["lib.py"] = {"functions": [{"id": "f", "name": "f", "params": 0}]}
    assert edges_for_file(prepare(list(facts), facts), "main.py")[0]["callee"] == "f"
    facts["main.py"]["call_sites"][0]["receiver_text"] = "other"
    assert edges_for_file(prepare(list(facts), facts), "main.py")[0]["kind"] == "opaque"


def test_type_and_bound_namespace_receivers_resolve_owned_methods():
    facts = _facts("Math", "max")
    facts["main.py"]["types"] = [{"id": "math", "name": "Math", "kind": "class"}]
    facts["main.py"]["functions"] += [
        {"id": "max", "name": "max", "owner": "Math", "params": 0}
    ]
    assert edges_for_file(prepare(list(facts), facts), "main.py")[0]["callee"] == "max"

    facts = _facts("Type", "Type::new")
    facts["main.py"]["types"] = [{"id": "type", "name": "Type", "kind": "class"}]
    facts["main.py"]["functions"] += [
        {"id": "new", "name": "new", "owner": "Type", "params": 0}
    ]
    assert edges_for_file(prepare(list(facts), facts), "main.py")[0]["callee"] == "new"

    facts = _facts("ns.Foo", "f", [{"module": "ns", "alias": "ns"}])
    facts["foo.py"] = {
        "types": [{"id": "foo", "name": "Foo", "kind": "class"}],
        "functions": [{"id": "method", "name": "f", "owner": "Foo", "params": 0}],
    }
    facts["main.py"]["imports"][0]["module"] = "foo"
    edge = edges_for_file(prepare(list(facts), facts), "main.py")[0]
    assert edge["callee"] == "method" and edge["pass"] == "receiver"  # noqa: S105 - The pass field is resolver metadata in test data.


def test_self_this_variables_external_and_ambiguity():
    facts = _facts("self", "f")
    facts["main.py"]["functions"] += [
        {"id": "method", "name": "f", "owner": "Thing", "params": 0}
    ]
    facts["main.py"]["call_sites"][0]["caller"] = "method"
    assert (
        edges_for_file(prepare(list(facts), facts), "main.py")[0]["callee"] == "method"
    )
    facts["main.py"]["call_sites"][0]["receiver_text"] = "this"
    assert (
        edges_for_file(prepare(list(facts), facts), "main.py")[0]["callee"] == "method"
    )
    facts["main.py"]["call_sites"][0]["receiver_text"] = "variable"
    assert edges_for_file(prepare(list(facts), facts), "main.py")[0]["kind"] == "opaque"

    facts = _facts("ext", "f", [{"module": "missing", "alias": "ext"}])
    assert (
        edges_for_file(prepare(list(facts), facts), "main.py")[0]["kind"] == "external"
    )

    facts = _facts("mod", "f", [{"module": "lib", "alias": "mod"}])
    facts["lib.py"] = {
        "functions": [
            {"id": "f1", "name": "f", "params": 0},
            {"id": "f2", "name": "f", "params": 0},
        ]
    }
    assert (
        edges_for_file(prepare(list(facts), facts), "main.py")[0]["kind"] == "ambiguous"
    )


def test_python_bound_method_arity_drops_receiver_and_keeps_missing_methods_opaque():
    facts = {
        "main.py": {
            "functions": [
                {"id": "caller", "name": "caller", "owner": "K", "params": 1},
                {"id": "method", "name": "n", "owner": "K", "params": 2},
            ],
            "call_sites": [
                {"caller": "caller", "name": "n", "receiver_text": "self", "arity": 1},
                {"caller": "caller", "name": "z", "receiver_text": "self", "arity": 1},
                {"caller": "caller", "name": "n", "receiver_text": "cls", "arity": 1},
            ],
        }
    }
    edges = edges_for_file(prepare(list(facts), facts), "main.py")
    assert [(edge["kind"], edge["callee"]) for edge in edges] == [
        ("resolved", "method"),
        ("opaque", None),
        ("resolved", "method"),
    ]


def test_python_bound_method_overloads_remain_ambiguous():
    facts = {
        "main.py": {
            "functions": [
                {"id": "caller", "name": "caller", "owner": "K", "params": 1},
                {"id": "one", "name": "n", "owner": "K", "params": 2},
                {"id": "two", "name": "n", "owner": "K", "params": 2},
            ],
            "call_sites": [
                {"caller": "caller", "name": "n", "receiver_text": "self", "arity": 1}
            ],
        }
    }
    edge = edges_for_file(prepare(list(facts), facts), "main.py")[0]
    assert (edge["kind"], edge["callee"]) == ("ambiguous", None)


def test_rust_self_receiver_resolves_enclosing_impl_method():
    facts = {
        "main.rs": {
            "functions": [
                {"id": "caller", "name": "caller", "owner": "K", "params": 1},
                {"id": "method", "name": "n", "owner": "K", "params": 1},
                {"id": "associated", "name": "s", "owner": "K", "params": 0},
            ],
            "call_sites": [
                {"caller": "caller", "name": "n", "receiver_text": "self", "arity": 0},
                {"caller": "caller", "name": "s", "receiver_text": "Self", "arity": 0},
            ],
        }
    }
    edges = edges_for_file(prepare(list(facts), facts), "main.rs")
    assert [(edge["kind"], edge["callee"]) for edge in edges] == [
        ("resolved", "method"),
        ("resolved", "associated"),
    ]


def test_go_receiver_variable_without_type_information_stays_opaque():
    facts = {
        "main.go": {
            "functions": [{"id": "caller", "name": "caller", "params": 0}],
            "call_sites": [
                {"caller": "caller", "name": "N", "receiver_text": "k", "arity": 0}
            ],
        },
        "other.go": {
            "functions": [{"id": "method", "name": "N", "owner": "K", "params": 1}]
        },
    }
    edge = edges_for_file(prepare(list(facts), facts), "main.go")[0]
    assert (edge["kind"], edge["callee"]) == ("opaque", None)


def test_dotted_python_import_matches_only_its_bound_module():
    facts = {
        "pkg/main.py": {
            "imports": [
                {"module": "pkg/helper", "text": "import pkg.helper", "line": 1}
            ],
            "call_sites": [
                {"name": "compute", "receiver_text": "pkg.helper", "arity": 0},
                {"name": "compute", "receiver_text": "pkg.other", "arity": 0},
            ],
        },
        "pkg/__init__.py": {},
        "pkg/helper.py": {
            "functions": [{"id": "compute", "name": "compute", "params": 0}]
        },
    }
    edges = edges_for_file(prepare(list(facts), facts), "pkg/main.py")
    assert [(edge["kind"], edge["callee"]) for edge in edges] == [
        ("resolved", "compute"),
        ("opaque", None),
    ]


def test_none_imports_are_tolerated():
    facts = {
        "main.py": {"imports": None, "call_sites": [{"name": "work", "arity": 0}]},
        "lib.py": {"imports": None, "functions": [{"id": "work", "name": "work"}]},
    }
    assert edges_for_file(prepare(list(facts), facts), "main.py")[0]["kind"] == "opaque"


def test_instance_member_chains_and_super_are_opaque():
    facts = _facts("self", "f")
    facts["main.py"]["functions"][0]["owner"] = "Thing"
    facts["main.py"]["functions"].append(
        {"id": "method", "name": "f", "owner": "Thing", "params": 0}
    )
    facts["main.py"]["call_sites"][0]["caller"] = "caller"
    for receiver in ("self.field", "this.field", "super"):
        facts["main.py"]["call_sites"][0]["receiver_text"] = receiver
        edge = edges_for_file(prepare(list(facts), facts), "main.py")[0]
        assert (edge["kind"], edge["callee"]) == ("opaque", None)

    for receiver in ("self", "this", "cls"):
        facts["main.py"]["call_sites"][0]["receiver_text"] = receiver
        assert (
            edges_for_file(prepare(list(facts), facts), "main.py")[0]["callee"]
            == "method"
        )


def test_import_binding_filters_module_calls_and_limits_owner_chains():
    facts = _facts("mod", "f", [{"module": "lib", "alias": "mod"}])
    facts["lib.py"] = {
        "functions": [{"id": "method", "name": "f", "owner": "Foo", "params": 0}]
    }
    edge = edges_for_file(prepare(list(facts), facts), "main.py")[0]
    assert (edge["kind"], edge["callee"]) == ("opaque", None)

    facts["lib.py"]["functions"].append({"id": "module-f", "name": "f", "params": 0})
    assert (
        edges_for_file(prepare(list(facts), facts), "main.py")[0]["callee"]
        == "module-f"
    )

    facts["main.py"]["call_sites"][0]["receiver_text"] = "mod.Foo.x"
    edge = edges_for_file(prepare(list(facts), facts), "main.py")[0]
    assert (edge["kind"], edge["callee"]) == ("opaque", None)

    facts["main.py"]["call_sites"][0]["receiver_text"] = "mod.Foo"
    facts["main.py"]["call_sites"][0]["name"] = "f"
    edge = edges_for_file(prepare(list(facts), facts), "main.py")[0]
    assert edge["callee"] == "method"


def test_old_fact_fallback_and_receiver_digest_dependencies():
    facts = _facts("placeholder", "f", [{"module": "lib", "alias": "mod"}])
    facts["main.py"]["call_sites"][0].pop("receiver_text")
    facts["main.py"]["call_sites"][0]["receiver"] = "mod"
    facts["lib.py"] = {
        "types": [{"id": "t", "name": "Foo", "kind": "class"}],
        "functions": [
            {"id": "f", "name": "f", "owner": "Foo", "params": 0},
            {"id": "module-f", "name": "f", "params": 0},
        ],
    }
    assert (
        edges_for_file(prepare(list(facts), facts), "main.py")[0]["callee"]
        == "module-f"
    )

    facts["main.py"]["call_sites"][0]["receiver_text"] = "mod.Foo"
    before = prepare(list(facts), facts)
    edit = {
        **facts,
        "lib.py": {
            **facts["lib.py"],
            "types": [{"id": "t2", "name": "Foo", "kind": "class"}],
        },
    }
    after = prepare(list(edit), edit)
    assert digest_for_file(before, "main.py") != digest_for_file(after, "main.py")
    edit["lib.py"] = {"functions": [{"id": "unrelated", "name": "other", "params": 0}]}
    unrelated = prepare(list(edit), edit)
    assert digest_for_file(after, "main.py") != digest_for_file(unrelated, "main.py")
    unrelated_facts = {
        **facts,
        "other.py": {"functions": [{"id": "x", "name": "unrelated"}]},
    }
    unrelated = prepare(list(unrelated_facts), unrelated_facts)
    assert digest_for_file(before, "main.py") == digest_for_file(unrelated, "main.py")
