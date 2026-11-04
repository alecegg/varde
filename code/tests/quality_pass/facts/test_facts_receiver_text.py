import pytest
from varde_code.quality_pass.facts import extract_facts


@pytest.mark.parametrize(
    ("language", "path", "source", "self_name"),
    [
        (
            "python",
            "sample.py",
            "def run():\n x.f(); a.b.f(); self.f(); f().g(); plain()\n",
            "self",
        ),
        (
            "typescript",
            "sample.ts",
            "function run(){ x.f(); a.b.f(); this.f(); f().g(); plain(); }",
            "this",
        ),
        (
            "java",
            "Sample.java",
            (
                "class Sample { void run(){ x.f(); a.b.f(); this.f(); f().g(); "
                "plain(); Math.max(1, 2); } }"
            ),
            "this",
        ),
        (
            "csharp",
            "Sample.cs",
            (
                "class Sample { void Run(){ x.F(); a.b.F(); this.F(); "
                "F().G(); Plain(); } }"
            ),
            "this",
        ),
        (
            "go",
            "sample.go",
            "package p\nfunc run(){ x.F(); a.b.F(); pkg.F(); plain() }",
            None,
        ),
        (
            "rust",
            "sample.rs",
            "fn run(){ x.f(); a.b.f(); self.f(); f().g(); plain(); Type::new(); }",
            "self",
        ),
        (
            "cpp",
            "sample.cpp",
            (
                "void run(){ x.f(); a.b.f(); p->f(); Foo::bar(); ns::F::g(); "
                "f().g(); plain(); }"
            ),
            None,
        ),
    ],
)
def test_call_sites_capture_simple_receivers_without_changing_legacy_receiver(
    language, path, source, self_name
):
    calls = extract_facts(source, language, path)["call_sites"]
    texts = [call["receiver_text"] for call in calls]
    assert "x" in texts
    assert "a.b" in texts
    assert None in texts
    plain_name = "Plain" if language == "csharp" else "plain"
    plain_call = next(call for call in calls if call["name"] == plain_name)
    assert plain_call["receiver_text"] is None
    if language != "go":
        complex_name = "G" if language == "csharp" else "g"
        complex_call = next(call for call in calls if call["name"] == complex_name)
        assert complex_call["receiver_text"] is None
    assert all(
        call["receiver"] is None
        for call in calls
        if call["receiver_text"] in {"x", "a.b"}
    )
    if self_name and language in {"python", "typescript", "java", "csharp"}:
        assert (
            next(call for call in calls if call["receiver_text"] == self_name)[
                "receiver"
            ]
            == "self"
        )
    elif self_name:
        assert (
            next(call for call in calls if call["receiver_text"] == self_name)[
                "receiver"
            ]
            is None
        )
    else:
        assert all(call["receiver"] is None for call in calls)

    if language == "cpp":
        assert "p" in texts
        assert "Foo" in texts
        assert "ns.F" in texts
    elif language == "go":
        assert "pkg" in texts
    elif language == "rust":
        assert "Type" in texts
    elif language == "java":
        assert "Math" in texts
    assert all("receiver_text" in call for call in calls)


def test_call_result_receivers_are_not_reported_as_identifier_chains():
    facts = extract_facts("def run():\n f().g()\n", "python", "sample.py")

    assert facts["call_sites"][0]["receiver_text"] is None
