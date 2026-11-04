from varde_code.quality_pass.facts import extract_facts


def _calls(source):
    facts = extract_facts(source, "csharp", "C.cs")
    return [
        (item["name"], item["receiver_text"], item["arity"], item.get("kind"))
        for item in facts["call_sites"]
    ]


def test_generic_method_call_keeps_plain_name_and_receiver():
    calls = _calls(
        "class C { void F() { b.Build<X<T>>(); Outcome.From<bool>(e); "
        "a.b.M<int, U>(); } }"
    )
    assert calls == [
        ("Build", "b", 0, None),
        ("From", "Outcome", 1, None),
        ("M", "a.b", 0, None),
    ]


def test_generic_call_on_an_expression_receiver_has_no_receiver_text():
    calls = _calls("class C { void F() { P().Handle<X>().Retry(); } }")
    assert sorted(calls) == [
        ("Handle", None, 0, None),
        ("P", None, 0, None),
        ("Retry", None, 0, None),
    ]


def test_target_typed_new_takes_the_declared_type():
    calls = _calls(
        """class C {
  readonly Field _f = new();
  Prop P { get; } = new(1);
  Ret Get() => new(this);
  Ret2 Make() { return new(a, b); }
  void M() { Local l = new(); var v = new(); Take(new()); }
}"""
    )
    assert [call for call in calls if call[3] == "new"] == [
        ("Field", None, 0, "new"),
        ("Prop", None, 1, "new"),
        ("Ret", None, 1, "new"),
        ("Ret2", None, 2, "new"),
        ("Local", None, 0, "new"),
    ]


def test_target_typed_new_in_a_lambda_return_is_not_attributed():
    calls = _calls("class C { Ret M() { f(() => { return new(); }); return null; } }")
    assert [call for call in calls if call[3] == "new"] == []
