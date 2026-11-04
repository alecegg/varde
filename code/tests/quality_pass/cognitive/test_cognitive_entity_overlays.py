"""Score-grade entity overlays: jumps, do-while, else-if and shared spans."""

from varde_code.complexity import function_complexities
from varde_code.extract.entity import extract_file
from varde_code.model import Entity, EntityKind, Span
from varde_code.quality_pass.cognitive import score_grade_complexities
from varde_code.quality_pass.cognitive.entities import equal_span_nesting_pairs


def score(language: str, path: str, source: str) -> dict[str, int]:
    parsed = extract_file(path, source, language)
    assert not parsed.has_parse_error
    return {
        item.name: item.cognitive
        for item in score_grade_complexities(
            parsed.entities, source=source, language=language, path=path
        )
    }


def fast(language: str, path: str, source: str) -> dict[str, int]:
    parsed = extract_file(path, source, language)
    assert not parsed.has_parse_error
    return {
        item.name: item.cognitive for item in function_complexities(parsed.entities)
    }


def java(body: str) -> str:
    return (
        f"class A {{ static boolean decide(boolean a, boolean b, boolean c) "
        f"{{ {body} }} }}"
    )


def test_labeled_break_adds_one_jump_increment_to_java():
    source = java("outer: while (a) { break outer; } return false;")

    # while +1; break to a label +1 (white paper B1: "break LABEL").
    assert fast("java", "decide.java", source)["decide"] == 1
    assert score("java", "decide.java", source)["decide"] == 2


def test_unlabeled_break_adds_no_jump_increment():
    source = java("while (a) { break; } return false;")

    # White paper B1: an early exit without a label is free.
    assert score("java", "decide.java", source)["decide"] == 1


def test_labeled_continue_adds_one_jump_increment():
    source = java("outer: while (a) { continue outer; } return false;")

    assert score("java", "decide.java", source)["decide"] == 2


def test_labeled_break_adds_one_jump_increment_to_typescript():
    source = (
        "function decide(a: boolean): boolean { outer: while (a) { break outer; } "
        "return false; }"
    )

    assert fast("typescript", "decide.ts", source)["decide"] == 1
    assert score("typescript", "decide.ts", source)["decide"] == 2


def test_go_labeled_break_is_counted_once():
    source = (
        "package p\nfunc decide(a bool) bool { outer: for a { break outer }; "
        "return false }"
    )

    # Go extraction already reports the labeled jump; the overlay must not add one.
    assert fast("go", "decide.go", source)["decide"] == 2
    assert score("go", "decide.go", source)["decide"] == 2


def test_java_do_while_contributes_its_own_structural_increment():
    source = java("do { a = !a; } while (b); return false;")

    assert fast("java", "decide.java", source)["decide"] == 0
    assert score("java", "decide.java", source)["decide"] == 1


def test_java_do_while_nested_in_if_receives_one_nesting_increment():
    source = java("if (a) { do { b = !b; } while (c); } return false;")

    # if +1; do-while +1 + one nesting.
    assert score("java", "decide.java", source)["decide"] == 3


def test_java_do_while_body_nests_its_own_flows():
    source = java("do { if (b) return true; } while (a); return false;")

    # do-while +1; nested if +1 + one nesting.
    assert score("java", "decide.java", source)["decide"] == 3


def test_cpp_else_if_is_one_hybrid_branch():
    source = (
        "static bool decide(bool a, bool b) "
        "{ if (a) return true; else if (b) return false; else return true; }"
    )

    # if, else-if and else each add one hybrid increment (white paper B1);
    # else-if takes no nesting increment of its own.
    assert fast("cpp", "decide.cpp", source)["decide"] == 5
    assert score("cpp", "decide.cpp", source)["decide"] == 3


def test_cpp_else_if_body_receives_one_nesting_level():
    source = (
        "static bool decide(bool a, bool b, bool c) "
        "{ if (a) return true; else if (b) { while (c) { break; } } return false; }"
    )

    # if +1; else-if +1; while +1 + one nesting.
    assert score("cpp", "decide.cpp", source)["decide"] == 4


def test_cpp_braced_else_around_if_is_still_an_else():
    source = (
        "static bool decide(bool a, bool b) "
        "{ if (a) return true; else { if (b) return false; } return false; }"
    )

    # if +1; else +1; the braced inner if +1 + one nesting.
    assert score("cpp", "decide.cpp", source)["decide"] == 4


def test_cpp_else_with_a_call_is_not_folded_as_else_if():
    source = (
        "static bool decide(bool a) { if (a) return true; else iffy(); return false; }"
    )

    # `else iffy();` is an else whose body is a call, not an else-if.
    assert fast("cpp", "decide.cpp", source)["decide"] == 2
    assert score("cpp", "decide.cpp", source)["decide"] == 2


def test_cpp_two_else_if_branches_each_add_one():
    source = (
        "static bool decide(bool a, bool b, bool c) "
        "{ if (a) return true; else if (b) return false; "
        "else if (c) return true; else return false; }"
    )

    assert score("cpp", "decide.cpp", source)["decide"] == 4


def test_python_block_wrapped_loop_keeps_its_nesting_increment():
    source = (
        "def decide(a, b, c):\n    if a:\n        for _ in b:\n"
        "            pass\n    return c\n"
    )

    # Extraction gives the if its body span, hiding one nesting level;
    # Sonar counts if +1 and the loop +1 + one nesting.
    assert fast("python", "decide.py", source)["decide"] == 2
    assert score("python", "decide.py", source)["decide"] == 3


def test_python_shared_span_chain_keeps_every_nesting_increment():
    source = (
        "def decide(a, b, c):\n    if a:\n        while b:\n"
        "            for _ in c:\n                return 1\n"
    )

    # if +1; while +1 + one nesting; for +1 + two nesting. Extraction gives
    # the if and while one shared span, hiding the while's nesting increment.
    assert fast("python", "decide.py", source)["decide"] == 5
    assert score("python", "decide.py", source)["decide"] == 6


def test_python_nested_if_keeps_the_shared_engine_value():
    source = (
        "def decide(a, b):\n    if a:\n        if b:\n"
        "            return 1\n    return 0\n"
    )

    # Nested ifs already nest correctly in the engine; no pair correction applies.
    assert fast("python", "decide.py", source)["decide"] == 3
    assert score("python", "decide.py", source)["decide"] == 3


def test_entity_overlays_are_deterministic():
    source = java("outer: while (a) { break outer; } do { b = !b; } while (c);")

    first = score("java", "decide.java", source)
    second = score("java", "decide.java", source)

    # while +1, labeled break +1, do-while +1.
    assert first == second == {"decide": 3}


def test_equal_span_nesting_pairs_are_limited_to_python():
    span = Span(0, 10, 1, 0, 1, 10)
    entities = [
        Entity(kind=EntityKind.CONTROL_FLOW, name="if_statement", file_id=0, span=span),
        Entity(
            kind=EntityKind.CONTROL_FLOW, name="for_statement", file_id=0, span=span
        ),
    ]

    # Only Python extraction is known to give a decision its body span; other
    # languages must not gain a nesting level from a shared span.
    assert equal_span_nesting_pairs(entities, "python") == [(0, 0, 10)]
    assert equal_span_nesting_pairs(entities, "java") == []
    assert equal_span_nesting_pairs(entities, None) == []
