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


def _call(name, arity, line, caller="m.py::main@1", receiver=None):
    return {
        "caller": caller,
        "name": name,
        "receiver": receiver,
        "arity": arity,
        "line": line,
    }


def _kinds(facts, path):
    return [
        (edge["kind"], edge["callee"])
        for edge in edges_for_file(prepare(list(facts), facts), path)
    ]


def test_call_with_fewer_arguments_resolves_default_parameters():
    facts = {
        "m.py": {
            "functions": [_fn("m.py", "main", 0), _fn("m.py", "helper", 3, 10, 12)],
            "call_sites": [_call("helper", 1, 5)],
        }
    }
    assert _kinds(facts, "m.py") == [("resolved", "m.py::helper@10")]


def test_exact_arity_wins_over_default_parameters():
    facts = {
        "m.py": {
            "functions": [
                _fn("m.py", "main", 0),
                _fn("m.py", "helper", 1, 10, 11),
                _fn("m.py", "helper", 3, 20, 21),
            ],
            "call_sites": [_call("helper", 1, 5)],
        }
    }
    assert _kinds(facts, "m.py") == [("resolved", "m.py::helper@10")]


def test_more_arguments_than_parameters_stays_unresolved():
    facts = {
        "m.py": {
            "functions": [_fn("m.py", "main", 0), _fn("m.py", "helper", 1, 10, 11)],
            "call_sites": [_call("helper", 3, 5)],
        }
    }
    assert _kinds(facts, "m.py")[0][0] != "resolved"


def test_self_call_resolves_method_with_default_parameters():
    facts = {
        "m.py": {
            "functions": [
                _fn("m.py", "main", 1, 1, 6, owner="K"),
                _fn("m.py", "run", 4, 10, 12, owner="K"),
            ],
            "call_sites": [_call("self.run", 1, 5, receiver="self")],
        }
    }
    assert _kinds(facts, "m.py") == [("resolved", "m.py::run@10")]


def test_nested_function_resolves_only_inside_its_caller():
    facts = {
        "m.py": {
            "functions": [
                _fn("m.py", "main", 1, 1, 9, owner="K"),
                _fn("m.py", "inner", 1, 3, 4, owner="K"),
                _fn("m.py", "other", 0, 12, 14, owner="K"),
            ],
            "call_sites": [
                _call("inner", 1, 6),
                _call("inner", 1, 13, caller="m.py::other@12"),
            ],
        }
    }
    assert [kind for kind, _ in _kinds(facts, "m.py")] == ["resolved", "opaque"]


def test_module_level_call_without_caller_resolves():
    facts = {
        "m.py": {
            "functions": [_fn("m.py", "helper", 1, 10, 11)],
            "call_sites": [{"caller": None, "name": "helper", "arity": 1, "line": 3}],
        }
    }
    assert _kinds(facts, "m.py") == [("resolved", "m.py::helper@10")]


def test_import_follows_package_reexport_to_defining_module():
    spec = {"module": "pkg", "text": "from pkg import widget", "line": 1}
    init_spec = {"module": ".impl", "text": "from .impl import widget", "line": 1}
    facts = {
        "app.py": {
            "functions": [_fn("app.py", "main", 0)],
            "imports": [spec],
            "call_sites": [_call("widget", 0, 5, caller="app.py::main@1")],
        },
        "pkg/__init__.py": {"imports": [init_spec]},
        "pkg/impl.py": {"functions": [_fn("pkg/impl.py", "widget", 0, 4, 5)]},
    }
    assert _kinds(facts, "app.py") == [("resolved", "pkg/impl.py::widget@4")]


def test_import_follows_star_reexport():
    spec = {"module": "pkg", "text": "from pkg import widget", "line": 1}
    init_spec = {"module": ".impl", "text": "from .impl import *", "line": 1}
    facts = {
        "app.py": {
            "functions": [_fn("app.py", "main", 0)],
            "imports": [spec],
            "call_sites": [_call("widget", 0, 5, caller="app.py::main@1")],
        },
        "pkg/__init__.py": {"imports": [init_spec]},
        "pkg/impl.py": {"functions": [_fn("pkg/impl.py", "widget", 0, 4, 5)]},
    }
    assert _kinds(facts, "app.py") == [("resolved", "pkg/impl.py::widget@4")]
