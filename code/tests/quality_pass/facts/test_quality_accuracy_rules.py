from varde_code.parse import parse_source_for_path
from varde_code.quality_pass import facts as facts_module
from varde_code.quality_pass.facts import extract_facts


def _walk(node):
    yield node
    for child in node.named_children:
        yield from _walk(child)


def test_csharp_verbatim_and_interpolated_strings_use_contract_weights():
    cases = (
        ('@"abcdefgh"', "verbatim_string_literal", 1),
        ('$"abcdefghi"', "interpolated_string_expression", 2),
        ('$@"abcdefghi"', "interpolated_string_expression", 2),
        ('@$"abcdefghi"', "interpolated_string_expression", 2),
    )
    for literal, node_type, weight in cases:
        source = f"class C {{ string F() {{ return {literal}; }} }}".encode()
        root = parse_source_for_path("csharp", "case.cs", source.decode()).root
        node = next(item for item in _walk(root) if item.type == node_type)

        assert facts_module._count_tokens(node, source) == (weight, weight)


def test_cpp_character_literals_are_atomic_including_escaped_forms():
    source = rb"int f(){ return u8'a' + L'\n' + '\x41' + '\''; }"
    root = parse_source_for_path("cpp", "case.cpp", source.decode()).root
    literals = [item for item in _walk(root) if item.type == "char_literal"]

    assert len(literals) == 4
    assert [facts_module._count_tokens(item, source) for item in literals] == [
        (1, 1),
        (1, 1),
        (1, 1),
        (1, 1),
    ]


def test_javascript_regex_literals_are_single_tokens():
    source = r"const r = /[/]+\//g;"
    facts = extract_facts(source, "javascript")

    assert facts["tokens"] == 5


def test_cpp_parameter_packs_each_count_once():
    cases = (
        ("template<typename... T> void f(T&&... xs) {}", 1),
        ("void f(int (*cb)(T...), T... xs) {}", 2),
        ("void f(T...) {}", 1),
    )
    for source, expected in cases:
        facts = extract_facts(source, "cpp")

        assert facts["functions"][0]["params"] == expected


def test_csharp_params_and_comment_only_lists_have_correct_counts():
    cases = (
        ("class C { void F(int a, params ReadOnlySpan<int> rest) {} }", 2),
        ("class C { void F(/* none */) {} }", 0),
        ('class C { void F(int a = G(1,2), string b = "x,y") {} }', 2),
        ("class C { void F<T>(T a, params T[] b) {} }", 2),
    )
    for source, expected in cases:
        facts = extract_facts(source, "csharp")

        assert facts["functions"][0]["params"] == expected


def test_rust_bodyless_methods_exclude_receivers_and_count_variadics():
    source = """trait Load {
    fn load<'a, U: Clone>(&self, x: &'a U, y: u8) -> u8 where U: Copy;
    fn take(self: Box<Self>, value: i32);
    fn empty(&mut self);
}
extern "C" { fn printf(format: *const u8, ...); }
"""
    facts = extract_facts(source, "rust")
    counts = {row["name"]: row["params"] for row in facts["functions"]}

    assert counts == {"load": 2, "take": 1, "empty": 0, "printf": 2}


def test_character_literals_share_the_data_literal_ratio_weight():
    source = b"int f() { return 'a' + 'b'; }"
    root = parse_source_for_path("cpp", "ratio.cpp", source.decode()).root
    body = next(item for item in _walk(root) if item.type == "compound_statement")

    assert facts_module._data_literal_ratio(body, source) == 2 / 3
