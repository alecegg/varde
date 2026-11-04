from varde_code.quality_pass.facts import extract_facts


def test_python_parameters_usage_exports_and_names():
    facts = extract_facts(
        "__all__ = ['public']\n"
        "def public(self, cls, /, *items, **options): return items\n"
        "def used(value): return private(value)\n"
        "def private(value): return value\n"
        "def util1(): return 1\n",
        "python",
    )
    rows = {row["name"]: row for row in facts["functions"]}

    assert rows["public"]["params"] == 4
    assert rows["public"]["file_private"] is False
    assert rows["used"]["file_private"] is False
    assert rows["private"]["file_private"] is True
    assert rows["util1"]["name_issues"] == ["vague", "numbered"]


def test_python_roles_accessors_fixture_handler_and_override():
    facts = extract_facts(
        "import pytest\n"
        "import pytest as pt\n"
        "from pytest import fixture as make_fixture\n"
        "from flask import Flask\n"
        "app = Flask(__name__)\n"
        "class Base:\n def render(self): return 1\n"
        "class Child(Base):\n"
        " @property\n def value(self): return self._value\n"
        " @value.setter\n def value(self, new): self._value = new\n"
        " def render(self): return 2\n"
        " def __str__(self): return 'child'\n"
        " @pt.fixture(scope='module')\n def resource(self): return 3\n"
        " @make_fixture(scope='function')\n def another_resource(self): return 3\n"
        " @pytest.fixture(scope='module')\n def direct_resource(self): return 3\n"
        " @app.route('/x', endpoint='endpoint')\n def endpoint(self): return 4\n"
        " @fixture(scope='module')\n def unverified(self): return 5\n",
        "python",
    )
    roles = {
        (row["owner"], row["name"]): row["exempt_role"] for row in facts["functions"]
    }

    assert roles[("Base", "render")] is None
    assert roles[("Child", "value")] == "accessor"
    assert roles[("Child", "render")] == "override"
    assert roles[("Child", "__str__")] == "override"
    assert roles[("Child", "resource")] == "fixture"
    assert roles[("Child", "another_resource")] == "fixture"
    assert roles[("Child", "direct_resource")] == "fixture"
    assert roles[("Child", "endpoint")] == "handler"
    assert roles[("Child", "unverified")] is None


def test_python_calls_and_markers_are_hand_derived():
    facts = extract_facts(
        "# @generated\ndef run(self, value):\n    return self.send(value, 2)\n",
        "python",
    )

    assert facts["markers"] == ["generated"]
    assert facts["excluded"] is None
    assert facts["call_sites"] == [
        {
            "caller": facts["functions"][0]["id"],
            "name": "send",
            "receiver": "self",
            "receiver_text": "self",
            "arity": 2,
            "line": 3,
        }
    ]
    vendored = extract_facts("# third-party source\ndef f(): return 1\n", "python")
    assert vendored["markers"] == ["vendored"]
    assert vendored["excluded"] is None


def test_python_comprehension_and_lambda_stay_in_enclosing_function_facts():
    facts = extract_facts(
        "def transform(values):\n"
        "    return list(map(lambda item: item + 1, [x for x in values if x]))\n",
        "python",
    )

    assert len(facts["functions"]) == 1
    assert facts["functions"][0]["name"] == "transform"
    assert facts["functions"][0]["tokens"] == 29


def test_python_minified_detection_marks_dense_single_line_source():
    source = "".join(f"value{index}={index};" for index in range(200))
    facts = extract_facts(source, "python", "dense.py")

    assert facts["excluded"] == "minified"


def test_python_visibility_is_owner_scoped_and_uses_python_conventions():
    facts = extract_facts(
        "__all__ = ('run',)\n"
        "__all__ += ['extra']\n"
        "__all__.extend(['extended'])\n"
        "def run(): return 1\n"
        "def extra(): return run()\n"
        "def extended(): return 1\n"
        "class Worker:\n"
        " def run(self): return 2\n"
        " def use(self): return self.run()\n"
        " def camelCase(self): return 3\n"
        " def __matmul__(self, other): return other\n",
        "python",
    )
    rows = {(row["owner"], row["name"]): row for row in facts["functions"]}

    assert rows[(None, "run")]["file_private"] is False
    assert rows[(None, "extra")]["file_private"] is False
    assert rows[(None, "extended")]["file_private"] is False
    assert rows[("Worker", "run")]["file_private"] is True
    assert rows[("Worker", "camelCase")]["name_issues"] == ["convention"]
    assert rows[("Worker", "__matmul__")]["exempt_role"] == "override"


def test_python_init_has_constructor_role_and_other_dunders_remain_overrides():
    facts = extract_facts(
        "class Box:\n"
        " def __init__(self, value): self.value = value\n"
        " def __str__(self): return str(self.value)\n",
        "python",
    )
    roles = {row["name"]: row["exempt_role"] for row in facts["functions"]}

    assert roles == {"__init__": "constructor", "__str__": "override"}


def test_python_nested_functions_are_not_base_overrides_and_keyword_only_params_count():
    facts = extract_facts(
        "class Base:\n def render(self): return 1\n"
        "class Middle(Base): pass\n"
        "class Child(Middle):\n"
        " def render(self, *, value, # ignored\n  extra=1):\n"
        "  def render(): return 2\n"
        "  return value\n",
        "python",
    )
    child_render = next(row for row in facts["functions"] if row["owner"] == "Child")
    nested_render = next(
        row
        for row in facts["functions"]
        if row["owner"] == "Child"
        and row["name"] == "render"
        and row["line"] != child_render["line"]
    )

    assert child_render["params"] == 3
    assert child_render["exempt_role"] == "override"
    assert nested_render["exempt_role"] is None


def test_python_module_call_receiver_uses_imported_alias():
    facts = extract_facts(
        "import os.path as path\n"
        "def join_parts(left, right): return path.join(left, right)\n",
        "python",
    )

    assert facts["call_sites"] == [
        {
            "caller": facts["functions"][0]["id"],
            "name": "join",
            "receiver": "mod",
            "receiver_text": "path",
            "arity": 2,
            "line": 2,
        }
    ]


def test_python_plain_imports_resolve_frameworks_and_module_receivers():
    facts = extract_facts(
        "import flask\n"
        "import os\n"
        "app = flask.Flask(__name__)\n"
        "@app.route('/x')\n"
        "def endpoint(): return os.path.join('a', 'b')\n",
        "python",
    )

    assert facts["functions"][0]["exempt_role"] == "handler"
    join_call = next(call for call in facts["call_sites"] if call["name"] == "join")
    assert join_call == {
        "caller": facts["functions"][0]["id"],
        "name": "join",
        "receiver": "mod",
        "receiver_text": "os.path",
        "arity": 2,
        "line": 5,
    }


def test_python_classmethod_async_test_roles_and_imported_module_receiver():
    facts = extract_facts(
        (
            "import os as operating_system\n"
            "class Worker:\n"
            " @classmethod\n"
            " async def load(cls, *, value): "
            "return operating_system.path.join(cls.make(value), 'x')\n"
            "class Standalone:\n def render(self): return 1\n"
        ),
        "python",
        "test_worker.py",
    )
    rows = {(row["owner"], row["name"]): row for row in facts["functions"]}
    load_calls = {call["name"]: call for call in facts["call_sites"]}

    assert rows[("Worker", "load")]["params"] == 2
    assert rows[("Standalone", "render")]["exempt_role"] is None
    assert load_calls["join"]["receiver"] == "mod"
    assert load_calls["make"]["receiver"] == "self"
