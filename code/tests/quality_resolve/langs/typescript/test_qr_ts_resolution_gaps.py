from varde_code.quality_resolve import edges_for_file, prepare


def _fn(path, name, params, line=1, end_line=2, owner=None):
    return {
        "id": f"{path}::{name}@{line}",
        "name": name,
        "params": params,
        "line": line,
        "end_line": end_line,
        "owner": owner,
    }


def _call(name, arity, line, caller, receiver=None, receiver_text=None):
    site = {"caller": caller, "name": name, "arity": arity, "line": line}
    site["receiver"] = receiver
    if receiver_text is not None:
        site["receiver_text"] = receiver_text
    return site


def _kinds(facts, path):
    return [
        (edge["kind"], edge["callee"])
        for edge in edges_for_file(prepare(list(facts), facts), path)
    ]


def test_javascript_default_import_binds_the_single_public_function():
    facts = {
        "a/helper.js": {"functions": [_fn("a/helper.js", "getThing", 1, 3, 9)]},
        "a/main.js": {
            "imports": [
                {
                    "module": "./helper.js",
                    "line": 1,
                    "text": 'import thing from "./helper.js"',
                }
            ],
            "functions": [_fn("a/main.js", "run", 0)],
            "call_sites": [_call("thing", 1, 5, "a/main.js::run@1")],
        },
    }
    assert _kinds(facts, "a/main.js") == [("resolved", "a/helper.js::getThing@3")]


def test_default_import_prefers_the_declaration_named_like_the_import():
    facts = {
        "helper.ts": {
            "functions": [
                _fn("helper.ts", "inferParser", 2, 3, 9),
                _fn("helper.ts", "other", 1, 10, 12),
            ]
        },
        "main.ts": {
            "imports": [
                {
                    "module": "./helper",
                    "line": 1,
                    "text": 'import inferParser from "./helper"',
                }
            ],
            "functions": [_fn("main.ts", "run", 0)],
            "call_sites": [_call("inferParser", 2, 5, "main.ts::run@1")],
        },
    }
    assert _kinds(facts, "main.ts") == [("resolved", "helper.ts::inferParser@3")]


def test_default_import_of_an_ambiguous_file_stays_unresolved():
    facts = {
        "helper.ts": {
            "functions": [
                _fn("helper.ts", "one", 1, 3, 9),
                _fn("helper.ts", "two", 1, 10, 12),
            ]
        },
        "main.ts": {
            "imports": [
                {
                    "module": "./helper",
                    "line": 1,
                    "text": 'import thing from "./helper"',
                }
            ],
            "functions": [_fn("main.ts", "run", 0)],
            "call_sites": [_call("thing", 1, 5, "main.ts::run@1")],
        },
    }
    assert _kinds(facts, "main.ts")[0][0] != "resolved"


def test_member_call_with_fewer_arguments_resolves_optional_parameter():
    facts = {
        "m.ts": {
            "functions": [
                _fn("m.ts", "main", 0, 1, 3, owner="Box"),
                _fn("m.ts", "query", 3, 5, 7, owner="Box"),
            ],
            "call_sites": [
                _call(
                    "query",
                    1,
                    2,
                    "m.ts::main@1",
                    receiver="self",
                    receiver_text="this",
                )
            ],
        }
    }
    assert _kinds(facts, "m.ts") == [("resolved", "m.ts::query@5")]


def test_unqualified_call_trusts_only_one_missing_argument():
    def facts(arity):
        return {
            "m.ts": {
                "functions": [_fn("m.ts", "main", 0), _fn("m.ts", "print", 3, 5, 7)],
                "call_sites": [_call("print", arity, 2, "m.ts::main@1")],
            }
        }

    assert _kinds(facts(2), "m.ts") == [("resolved", "m.ts::print@5")]
    assert _kinds(facts(1), "m.ts")[0][0] != "resolved"


def test_constructor_with_fewer_arguments_resolves_optional_parameter():
    facts = {
        "m.ts": {
            "functions": [
                _fn("m.ts", "main", 0),
                _fn("m.ts", "constructor", 2, 5, 7, owner="Query"),
            ],
            "types": [
                {
                    "id": "m.ts::Query#1",
                    "name": "Query",
                    "kind": "class",
                    "line": 4,
                    "qualifier": "",
                }
            ],
            "call_sites": [
                {
                    "caller": "m.ts::main@1",
                    "name": "Query",
                    "kind": "new",
                    "arity": 1,
                    "line": 2,
                }
            ],
        }
    }
    assert _kinds(facts, "m.ts") == [("resolved", "m.ts::constructor@5")]


def _constructor_facts(path, constructors):
    return {
        path: {
            "functions": [_fn(path, "main", 0), *constructors],
            "types": [
                {
                    "id": f"{path}::Query#1",
                    "name": "Query",
                    "kind": "class",
                    "line": 4,
                    "qualifier": "",
                }
            ],
            "call_sites": [
                {
                    "caller": f"{path}::main@1",
                    "name": "Query",
                    "kind": "new",
                    "arity": 2,
                    "line": 2,
                }
            ],
        }
    }


def test_overloaded_typescript_constructor_is_ambiguous():
    constructors = [
        _fn("m.ts", "constructor", 0, 5, 5, owner="Query"),
        _fn("m.ts", "constructor", 0, 6, 6, owner="Query"),
        _fn("m.ts", "constructor", 3, 7, 9, owner="Query"),
    ]
    assert _kinds(_constructor_facts("m.ts", constructors), "m.ts") == [
        ("ambiguous", None)
    ]


def test_repeated_constructors_outside_typescript_still_match_by_arity():
    constructors = [
        _fn("m.cs", "constructor", 1, 5, 5, owner="Query"),
        _fn("m.cs", "constructor", 2, 7, 9, owner="Query"),
    ]
    assert _kinds(_constructor_facts("m.cs", constructors), "m.cs") == [
        ("resolved", "m.cs::constructor@7")
    ]


def test_private_member_call_resolves_within_the_class():
    facts = {
        "m.js": {
            "functions": [
                _fn("m.js", "go", 0, 3, 6, owner="Cache"),
                _fn("m.js", "#load", 1, 8, 10, owner="Cache"),
            ],
            "call_sites": [
                {
                    "caller": "m.js::go@3",
                    "name": "#load",
                    "receiver": "self",
                    "receiver_text": None,
                    "arity": 1,
                    "line": 4,
                }
            ],
        }
    }
    assert _kinds(facts, "m.js") == [("resolved", "m.js::#load@8")]
