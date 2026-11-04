import time

from varde_code.quality_pass.facts import extract_facts


def test_call_owners_match_naive_smallest_enclosing_function():
    source = """\
def outer():
    outer_call()
    def inner():
        inner_call()
        return lambda: lambda_call()
    return inner()
"""
    facts = extract_facts(source, "python", "nested.py")
    functions = facts["functions"]
    expected = []
    for call in facts["call_sites"]:
        enclosing = [
            function
            for function in functions
            if function["line"] <= call["line"] <= function["end_line"]
        ]
        winner = min(
            enclosing,
            key=lambda function: function["end_line"] - function["line"],
            default=None,
        )
        expected.append(winner["id"] if winner else None)
    assert [call["caller"] for call in facts["call_sites"]] == expected


def test_extract_many_calls_with_many_functions_within_bound():
    source = "\n\n".join(
        f"def function_{function_index}():\n"
        + "\n".join(f"    target_{call_index}()" for call_index in range(10))
        for function_index in range(300)
    )
    started = time.perf_counter()
    facts = extract_facts(source, "python", "many_calls.py")
    assert len(facts["functions"]) == 300
    assert len(facts["call_sites"]) == 3000
    assert time.perf_counter() - started < 30
