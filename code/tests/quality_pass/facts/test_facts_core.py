from pathlib import Path
from types import SimpleNamespace

import varde_code.quality_pass.facts as facts_module
from varde_code.quality_pass.facts import extract_facts, quality_extractor_version


def test_tokens_exclude_comments_and_weight_strings():
    facts = extract_facts(
        """# comment words\ndef f(x):\n    return "abcdefghijk" + x\n""", "python"
    )
    short_string = extract_facts('def f():\n    return "a"\n', "python")
    long_string = extract_facts('def f():\n    return "abcdefghijklmno"\n', "python")
    capped_string = extract_facts(f'def f():\n    return "{"x" * 257}"\n', "python")

    assert facts["tokens"] == 11
    assert facts["functions"][0]["tokens"] == 11
    assert short_string["tokens"] == 7
    assert long_string["tokens"] == 8
    assert capped_string["tokens"] == 38
    assert facts["comment_parity"] == {"tokens": 11, "comment_tokens": 3}


def test_tokens_weight_python_prefixed_strings_by_content_length():
    raw = extract_facts('def f():\n    return r"abcdefghijklmnopqrstuvwx"\n', "python")
    byte = extract_facts(
        'def f():\n    return b"abcdefghijklmnopqrstuvwxyz0123456789"\n', "python"
    )
    formatted = extract_facts(
        'def f():\n    return f"abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJ"\n',
        "python",
    )

    # A function contributes six non-string tokens; string weights are ceil(len / 8).
    assert raw["tokens"] == 9  # 6 + ceil(24 / 8)
    assert byte["tokens"] == 11  # 6 + ceil(36 / 8)
    assert formatted["tokens"] == 12  # 6 + ceil(46 / 8)


def test_parameters_markers_minified_and_private_usage():
    source = (
        "# @generated\n# vendored source\ndef _hidden(a, b):\n    return a\n"
        "def used():\n    return _hidden(1, 2)\n"
    )
    facts = extract_facts(source, "python")

    hidden, used = facts["functions"]
    assert hidden["params"] == 2
    assert hidden["file_private"] is True
    assert used["file_private"] is False
    assert facts["markers"] == ["generated", "vendored"]
    assert facts["excluded"] is None
    assert facts["call_sites"][0] == {
        "caller": used["id"],
        "name": "_hidden",
        "receiver": None,
        "receiver_text": None,
        "arity": 2,
        "line": 6,
    }
    assert facts["call_coverage"] is None
    assert facts["unresolved_share"] is None
    assert facts["structure_confidence"] is None


def test_each_generated_marker_is_recorded_without_exclusion():
    generated = extract_facts("# @generated\ndef f():\n return 1\n", "python")
    vendored = extract_facts("# vendored source\ndef f():\n return 1\n", "python")

    assert generated["markers"] == ["generated"]
    assert generated["excluded"] is None
    assert vendored["markers"] == ["vendored"]
    assert vendored["excluded"] is None


def test_minified_detection_uses_median_code_tokens_per_line():
    line_49 = "\n".join(["x=x+1;" * 8 + "x"] * 3)
    line_50 = "\n".join(["x=x+1;" * 8 + "x;"] * 3)
    one_dense_line = "x=x+1;" * 8 + "x;\n\nx;\n"

    assert extract_facts(line_49, "javascript")["excluded"] is None
    assert extract_facts(line_50, "javascript")["excluded"] == "minified"
    assert extract_facts(one_dense_line, "javascript")["excluded"] is None


def test_accessor_requires_one_statement_and_ids_are_stable():
    first = extract_facts(
        "def get_x(self):\n    return self.x\ndef other():\n    return 1\n", "python"
    )
    reordered = extract_facts(
        "def other():\n    return 1\ndef get_x(self):\n    return self.x\n", "python"
    )
    first_ids = {f["name"]: f["id"] for f in first["functions"]}
    reordered_ids = {f["name"]: f["id"] for f in reordered["functions"]}

    assert first_ids == reordered_ids
    assert (
        next(f for f in first["functions"] if f["name"] == "get_x")["exempt_role"]
        == "accessor"
    )
    assert first["functions"][0]["tokens"] == 10


def test_multistatement_accessor_is_not_exempt_and_data_function_is_detected():
    facts = extract_facts(
        (
            "def not_getter(self):\n    value = self.x\n    return value\n"
            'def table():\n    """a very long embedded literal value '
            'used as data for the caller"""\n'
        ),
        "python",
    )

    assert facts["functions"][0]["exempt_role"] is None
    assert facts["data_functions"] == [facts["functions"][1]["id"]]


def test_explicit_exports_and_extractor_version(monkeypatch):
    monkeypatch.setattr(
        facts_module,
        "language_module",
        lambda language: SimpleNamespace(
            exported_names=lambda root, source: {"public"}
        ),
    )
    facts = extract_facts(
        (
            '__all__ = ["public"]\ndef public():\n    return helper_func()\n'
            "def helper_func():\n    return 2\n"
        ),
        "python",
    )

    assert facts["functions"][0]["file_private"] is False
    assert facts["functions"][1]["file_private"] is True
    assert quality_extractor_version() == quality_extractor_version()
    assert quality_extractor_version().startswith("blake2b-")


def test_version_digest_changes_when_any_dependency_bytes_change(tmp_path):
    source = tmp_path / "extractor-data.json"
    source.write_text("first", encoding="utf-8")
    first = facts_module._version_digest([source], {}, tmp_path)
    first_version = facts_module._version_digest(
        [source], {"tree-sitter": "1.0"}, tmp_path
    )
    source.write_text("second", encoding="utf-8")

    assert facts_module._version_digest([source], {}, tmp_path) != first
    assert (
        facts_module._version_digest([source], {"tree-sitter": "2.0"}, tmp_path)
        != first_version
    )


def test_extractor_version_hashes_the_facts_package_and_parser_sources(monkeypatch):
    captured = {}

    def fake_digest(paths, versions, root):
        captured["paths"] = {path.relative_to(root) for path in paths}
        captured["versions"] = versions
        return "blake2b-captured"

    monkeypatch.setattr(facts_module, "_version_digest", fake_digest)
    facts_module.quality_extractor_version.cache_clear()
    try:
        version = facts_module.quality_extractor_version()
    finally:
        facts_module.quality_extractor_version.cache_clear()

    assert version == "blake2b-captured"
    assert Path("quality_pass/facts/__init__.py") in captured["paths"]
    assert Path("quality_pass/langs/python/__init__.py") in captured["paths"]
    assert Path("parse.py") in captured["paths"]
    assert Path("extract/entity.py") in captured["paths"]
    assert set(captured["versions"]) == {"tree-sitter", "tree-sitter-language-pack"}


def test_parameters_for_python_go_and_single_identifier_arrow():
    python = extract_facts("class A:\n def f(self, x, y):\n  return x\n", "python")
    go = extract_facts(
        "package p\ntype T struct{}\nfunc (t *T) M(a int, b string) {}\n", "go"
    )
    typescript = extract_facts("const f = x => x;", "typescript")

    assert python["functions"][0]["params"] == 3
    assert go["functions"][0]["params"] == 2
    assert typescript["functions"][0]["params"] == 1


def test_roles_setter_constructor_and_rejected_unverified_roles():
    source = (
        "class Box:\n def __init__(self, value):\n  self.value = value\n"
        " def set_value(self, value):\n  self.value = value\n"
        " def bad(self, value):\n  self.value = other\n"
    )
    facts = extract_facts(source, "python")

    assert [row["exempt_role"] for row in facts["functions"]] == [
        "constructor",
        "accessor",
        None,
    ]


def test_language_role_hook_requires_import_and_same_name_base_evidence(monkeypatch):
    source = (
        "from framework import route\nclass Base:\n def render(self): return 1\n"
        "class Child(Base):\n @route\n def route(self): return 1\n"
        " def render(self): return 2\n@route\ndef plain(): return 1\n"
    )

    def verified_role(record, node, body, text):
        text = text.decode()
        if (
            record["name"] == "route"
            and record["owner"] == "Child"
            and "from framework import route" in text
        ):
            return "handler"
        if (
            record["name"] == "render"
            and record["owner"] == "Child"
            and "class Base" in text
        ):
            return "override"
        return None

    monkeypatch.setattr(
        facts_module,
        "language_module",
        lambda language: SimpleNamespace(verified_role=verified_role),
    )
    facts = extract_facts(source, "python")
    roles = {
        (row["owner"], row["name"]): row["exempt_role"] for row in facts["functions"]
    }

    assert roles[("Base", "render")] is None
    assert roles[("Child", "route")] == "handler"
    assert roles[("Child", "render")] == "override"
    assert roles[(None, "plain")] is None


def test_call_shapes_have_resolved_syntax_but_unresolved_receivers_are_null():
    java = extract_facts("class A { void f() { this.g(1); } void g(int x) {} }", "java")
    python = extract_facts("def f():\n return g(x for x in values)\n", "python")

    assert java["call_sites"][0]["name"] == "g"
    assert java["call_sites"][0]["receiver"] == "self"
    assert java["call_sites"][0]["arity"] == 1
    assert python["call_sites"][0]["arity"] == 1


def test_name_issues_follow_word_list_and_numbered_rules():
    facts = extract_facts(
        (
            "def util1():\n return 1\ndef get_x():\n return 1\n"
            "def is_ok():\n return True\ndef __init__():\n return None\n"
            "def cfg():\n return 1\ndef zz():\n return 1\n"
            "def this_is_a_very_long_function_name_with_many_words():\n return 1\n"
        ),
        "python",
    )
    issues = {row["name"]: row["name_issues"] for row in facts["functions"]}

    assert issues["util1"] == ["vague", "numbered"]
    assert issues["get_x"] == []
    assert issues["is_ok"] == []
    assert "convention" not in issues["__init__"]
    assert issues["cfg"] == ["abbreviation"]
    assert "single_char" in issues["zz"]
    assert "long" in issues["this_is_a_very_long_function_name_with_many_words"]


def test_typescript_string_type_is_not_a_string_literal():
    string_type = extract_facts('let value: string = "x";', "typescript")
    number_type = extract_facts('let value: number = "x";', "typescript")

    assert string_type["tokens"] == number_type["tokens"]


def test_numeric_table_function_counts_data_literals():
    facts = extract_facts("def table():\n    return [1, 2, 3, 4]\n", "python")

    assert facts["data_functions"] == [facts["functions"][0]["id"]]


def test_cognitive_value_and_path_independent_content_hash():
    source = "def choose(x):\n    if x:\n        return 1\n    return 0\n"
    first = extract_facts(source, "python", "src/first.py")
    second = extract_facts(source, "python", "src/second.py")

    assert first["functions"][0]["cognitive"] > 0
    assert first["content_hash"] == second["content_hash"]
    assert first["functions"][0]["id"] != second["functions"][0]["id"]


def test_nested_same_name_and_decorated_functions_use_their_own_nodes():
    facts = extract_facts(
        (
            "@decorator\ndef same():\n    def same():\n"
            "        return 1\n    return same()\n"
        ),
        "python",
    )
    outer, inner = facts["functions"]

    assert outer["line"] == 2
    assert inner["line"] == 3
    assert outer["tokens"] > inner["tokens"]
    assert facts["call_sites"][0]["caller"] == outer["id"]


def test_lang_directory_discovery_normalizes_and_rejects_invalid_names(monkeypatch):
    from varde_code.quality_pass import langs

    class Entry:
        name = "python"

        def is_dir(self):
            return True

    monkeypatch.setattr(
        langs, "files", lambda package: SimpleNamespace(iterdir=lambda: [Entry()])
    )
    monkeypatch.setattr(
        langs, "import_module", lambda name: SimpleNamespace(__name__=name)
    )

    module = langs.language_module("py")
    assert module is not None
    assert module.__name__ == "varde_code.quality_pass.langs.python"
    assert langs.language_module("__pycache__") is None
    assert langs.language_module("not-a-language") is None

    def no_package(package):
        raise FileNotFoundError("missing package")

    monkeypatch.setattr(langs, "files", no_package)
    assert langs.language_module("py") is None


def test_unmatched_function_node_is_diagnostic_not_root_proxy(monkeypatch):
    monkeypatch.setattr(facts_module, "_function_nodes", lambda root: [])
    facts = extract_facts("def f():\n return 1\n", "python")

    assert facts["functions"][0]["tokens"] == 0
    assert facts["diagnostics"] == ["function node not found: f:1"]


def test_export_identity_is_owner_scoped(monkeypatch):
    monkeypatch.setattr(
        facts_module,
        "language_module",
        lambda language: SimpleNamespace(
            exported_names=lambda root, source: {("A", "read")}
        ),
    )
    source = (
        "class A:\n def read(self): return 1\nclass B:\n"
        " def read(self): return 2\ndef use(b): return b.read()\n"
    )
    facts = extract_facts(source, "python")
    private = {
        (row["owner"], row["name"]): row["file_private"] for row in facts["functions"]
    }

    assert private[("A", "read")] is False
    assert private[("B", "read")] is True


def test_recovery_and_hashes_are_deterministic():
    malformed = extract_facts("def broken(:\n    return 1\n", "python")
    valid = extract_facts("def f():\n    return 1\n", "python")
    repeated = extract_facts("def f():\n    return 1\n", "python")

    assert malformed["excluded"] is None
    assert malformed["diagnostics"] == ["parse contains errors"]
    assert valid["content_hash"] == repeated["content_hash"]
    assert valid["content_hash"] != malformed["content_hash"]
    assert valid == repeated


def test_language_plugin_hooks_supply_exports_and_receivers(monkeypatch):
    plugin = SimpleNamespace(
        exported_names=lambda root, source: {"helper"},
        file_private=lambda record, root, source, references: False,
        call_site=lambda node, source: {"receiver": "mod"},
        verified_role=lambda record, node, body, source: None,
    )
    monkeypatch.setattr(facts_module, "language_module", lambda language: plugin)
    facts = extract_facts("def helper():\n return target.run()\n", "python")

    assert facts["functions"][0]["file_private"] is False
    assert facts["call_sites"][0]["receiver"] == "mod"
    assert facts["call_sites"][0]["receiver_text"] == "target"
