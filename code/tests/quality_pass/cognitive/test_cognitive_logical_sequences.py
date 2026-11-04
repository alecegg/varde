"""Score-grade logical-operator sequences against Sonar count expectations."""

import pytest
from varde_code.complexity import function_complexities
from varde_code.extract.entity import extract_file
from varde_code.quality_pass.cognitive import score_grade_complexities


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


# Expected values follow SonarJava's own cognitive-complexity expectations in
# java-frontend/src/test/files/metrics/CognitiveComplexity.java, which apply the
# white paper's "each new sequence of like operators" rule: one increment per run
# of && or ||, in evaluation order.
JAVA_CASES = [
    ("return a && b || foo(b && c);", 3),
    ("return a && (b || c) || d;", 2),
    ("if (a && b || c || d) { }", 3),
    ("if (a && b || c && d || e) { }", 5),
    ("if (a || b && c || d && e) { }", 5),
    ("if (a && b && c || d || e) { }", 3),
    ("return f(a && b) && (c || d);", 3),
]


@pytest.mark.parametrize(("body", "expected"), JAVA_CASES)
def test_java_logical_sequences_match_sonar_expectations(body, expected):
    source = (
        f"class A {{ static boolean decide(boolean a, boolean b, boolean c, "
        f"boolean d, boolean e) {{ {body} return false; }} }}"
    )

    assert score("java", "decide.java", source)["decide"] == expected


def test_java_engine_undercounts_mixed_operator_runs_without_the_overlay():
    source = (
        "class A { static boolean decide(boolean a, boolean b, boolean c, boolean d) "
        "{ return a && b || foo(b && c); } }"
    )

    # The engine reports one sequence for the outer expression; Sonar counts two
    # there plus one in the call argument.
    assert fast("java", "decide.java", source)["decide"] == 1
    assert score("java", "decide.java", source)["decide"] == 3


MIXED_BOOLEAN = {
    "typescript": (
        "function decide(a: boolean, b: boolean, c: boolean, d: boolean): "
        "boolean { if (a && b || c && d) return true; return false; }"
    ),
    "java": (
        "class A { static boolean decide(boolean a, boolean b, boolean c, "
        "boolean d) { if (a && b || c && d) return true; return false; } }"
    ),
    "go": (
        "package p\nfunc decide(a, b, c, d bool) bool { if a && b || c && d { "
        "return true }; return false }"
    ),
    "csharp": (
        "class A { static bool decide(bool a, bool b, bool c, bool d) { "
        "if (a && b || c && d) return true; return false; } }"
    ),
    "cpp": (
        "static bool decide(bool a, bool b, bool c, bool d) { "
        "if (a && b || c && d) return true; return false; }"
    ),
}
EXTENSIONS = {
    "typescript": "ts",
    "java": "java",
    "go": "go",
    "csharp": "cs",
    "cpp": "cpp",
}


@pytest.mark.parametrize("language", sorted(MIXED_BOOLEAN))
def test_mixed_operator_runs_count_three_sequences_in_every_language(language):
    source = MIXED_BOOLEAN[language]
    path = f"decide.{EXTENSIONS[language]}"

    # if +1; `&&`, `||`, `&&` are three like-operator runs.
    assert score(language, path, source)["decide"] == 4


@pytest.mark.parametrize("language", sorted(MIXED_BOOLEAN))
def test_parenthesized_nested_operator_is_a_second_sequence(language):
    bodies = {
        "typescript": (
            "function decide(a: boolean, b: boolean, c: boolean): boolean { "
            "return a && (b || c); }"
        ),
        "java": (
            "class A { static boolean decide(boolean a, boolean b, boolean c) { "
            "return a && (b || c); } }"
        ),
        "go": "package p\nfunc decide(a, b, c bool) bool { return a && (b || c) }",
        "csharp": (
            "class A { static bool decide(bool a, bool b, bool c) { "
            "return a && (b || c); } }"
        ),
        "cpp": "static bool decide(bool a, bool b, bool c) { return a && (b || c); }",
    }

    # `&&` then `||`: two like-operator runs, and neither gets nesting.
    assert (
        score(language, f"decide.{EXTENSIONS[language]}", bodies[language])["decide"]
        == 2
    )


def test_python_logical_sequences_are_left_to_the_shared_engine():
    source = (
        "def decide(a, b, c, d):\n    if a and b or c and d:\n"
        "        return True\n    return False\n"
    )

    # Python extraction already keeps operator runs; the overlay must not change it.
    assert score("python", "decide.py", source) == fast("python", "decide.py", source)
    assert score("python", "decide.py", source)["decide"] == 4


NESTED_CALLABLE = {
    "typescript": (
        "function decide(a: boolean, b: boolean): boolean { const r = () => { "
        "if (a && b) { return; } }; return false; }"
    ),
    "java": (
        "class A { static boolean decide(boolean a, boolean b) { Runnable r = "
        "() -> { if (a && b) { return; } }; return false; } }"
    ),
    "go": (
        "package p\nfunc decide(a, b bool) bool { r := func() { if a && b { "
        "_ = true } }; _ = r; return false }"
    ),
    "csharp": (
        "class A { static bool decide(bool a, bool b) { System.Action r = "
        "() => { if (a && b) { return; } }; return false; } }"
    ),
    "cpp": (
        "static bool decide(bool a, bool b) { auto r = [&]() { "
        "if (a && b) { return; } }; return false; }"
    ),
}


@pytest.mark.parametrize("language", sorted(NESTED_CALLABLE))
def test_logical_sequence_inside_a_lambda_counts_once_per_scored_callable(language):
    source = NESTED_CALLABLE[language]
    path = f"decide.{EXTENSIONS[language]}"
    parsed = extract_file(path, source, language)
    assert not parsed.has_parse_error
    results = {
        item.name: item.cognitive
        for item in score_grade_complexities(
            parsed.entities, source=source, language=language, path=path
        )
    }

    # White paper: a lambda adds no increment but raises the nesting level, so the
    # enclosing function scores if +1 + one nesting plus the `&&` run = 3. The
    # lambda scored as its own callable is if +1 plus the same run = 2. The run is
    # attributed to both spans, never counted twice inside one of them.
    assert results["decide"] == 3
    assert sorted(
        value for name, value in results.items() if name.startswith("<anonymous>")
    ) == [2]
