from varde_code.quality_pass.facts import extract_facts


def test_creation_sites_have_constructor_shape():
    for language, source in (
        ("java", "class A { void f() { new B(1); new a.b.C(); } }"),
        ("csharp", "class A { void F() { new B(1); } }"),
        ("typescript", "class A { f() { new B(1); } }"),
        ("cpp", "class A { void f() { new B(1); } }"),
    ):
        calls = [
            call
            for call in extract_facts(source, language, "x")["call_sites"]
            if call.get("kind") == "new"
        ]
        assert calls
        assert calls[0]["name"] == "B"
        assert calls[0]["arity"] == 1
        assert calls[0]["receiver"] is None
        assert calls[0]["receiver_text"] is None or calls[0]["receiver_text"] == "a.b"


def test_creation_qualified_type_uses_last_name_and_prefix():
    calls = extract_facts("class A { void f() { new a.b.C(); } }", "java")["call_sites"]
    site = next(call for call in calls if call.get("kind") == "new")
    assert (site["name"], site["receiver_text"], site["arity"]) == ("C", "a.b", 0)
