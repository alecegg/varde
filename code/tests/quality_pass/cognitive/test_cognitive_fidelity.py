import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from varde_code.complexity import function_complexities
from varde_code.extract.entity import extract_file
from varde_code.index.build import build
from varde_code.model import ExtractOutput
from varde_code.quality_pass.cognitive import score_grade_complexities

pytestmark = pytest.mark.slow

FIXTURES = Path(__file__).parent / "fixtures" / "cognitive"
LANGUAGES = ("python", "typescript", "java", "go", "rust", "csharp", "cpp")
EXTENSIONS = {
    "python": "py",
    "typescript": "ts",
    "java": "java",
    "go": "go",
    "rust": "rs",
    "csharp": "cs",
    "cpp": "cpp",
}
EXPECTED_RATES = {
    # Measured on the hand-derived fixtures. The 95% plan target is reported
    # separately and deliberately is not an assertion. Go's one mismatch is the
    # documented SonarGo error-guard exemption (see the triage note).
    "python": (30, 30, 30),
    "typescript": (30, 30, 30),
    "java": (30, 30, 30),
    "go": (29, 30, 29),
    "rust": (30, 30, 30),
    "csharp": (30, 30, 30),
    "cpp": (30, 30, 30),
}
# Fixtures whose score-grade value intentionally differs from the fast engine but
# that do not carry the fixture `overlay` flag. Declaring them here keeps the
# fixtures immutable and still fails the parity test on any other value change.
EXTRA_OVERLAY_CASES = frozenset(
    {
        ("python", "c12_if_with_loop"),
        ("typescript", "c08_mixed_boolean"),
        ("typescript", "c25_labeled_jump"),
        ("typescript", "c26_boolean_operator_sequences"),
        ("java", "c08_mixed_boolean"),
        ("java", "c24_do_while"),
        ("java", "c25_labeled_jump"),
        ("java", "c27_language_idiom"),
        ("go", "c08_mixed_boolean"),
        ("go", "c26_boolean_operator_sequences"),
        ("csharp", "c08_mixed_boolean"),
        ("csharp", "c26_boolean_operator_sequences"),
        ("cpp", "c04_if_elif_else"),
        ("cpp", "c05_three_way_chain"),
        ("cpp", "c08_mixed_boolean"),
    }
)


def overlay_case_names(language: str, fixture: dict) -> set[str]:
    """Names whose score-grade value the overlay is expected to change."""
    flagged = {
        item["name"] for item in fixture["functions"] if item.get("overlay", False)
    }
    declared = {
        name for case_language, name in EXTRA_OVERLAY_CASES if case_language == language
    }
    return flagged | declared


def load_fixture(language: str) -> dict:
    return json.loads((FIXTURES / f"{language}.json").read_text())


def measure_fidelity(language: str) -> dict[str, object]:
    fixture = load_fixture(language)
    extracted = extract_file(
        f"fixture.{EXTENSIONS[language]}", fixture["source"], language
    )
    assert not extracted.has_parse_error
    measured = score_grade_complexities(
        extracted.entities,
        source=fixture["source"],
        language=language,
        path=f"fixture.{EXTENSIONS[language]}",
    )
    actual = {
        item.name: item.cognitive
        for item in measured
        if not item.name.startswith("<anonymous>")
    }
    expected = {item["name"]: item["expected"] for item in fixture["functions"]}
    assert len(expected) == 30
    exact = sum(actual.get(name) == value for name, value in expected.items())
    within_one = sum(
        name in actual and abs(actual[name] - value) <= 1
        for name, value in expected.items()
    )
    mismatches = [
        f"{name}: expected {value}, got {actual.get(name, 'missing')}"
        for name, value in expected.items()
        if actual.get(name) != value
    ]
    return {
        "language": language,
        "exact": exact,
        "within_one": within_one,
        "total": len(expected),
        "exact_rate": exact / len(expected),
        "within_one_rate": within_one / len(expected),
        "mismatches": mismatches,
    }


@pytest.mark.parametrize("language", LANGUAGES)
def test_hand_derived_sonar_fixture_rates(language):
    rates = measure_fidelity(language)
    print(
        f"{language}: exact={rates['exact']}/{rates['total']} "
        f"({rates['exact_rate']:.1%}); within_one={rates['within_one']}/"
        f"{rates['total']} ({rates['within_one_rate']:.1%})"
    )
    if rates["mismatches"]:
        print("  mismatches: " + "; ".join(cast("list[str]", rates["mismatches"])))
    # Accuracy is reported, never used to retune or remove a difficult fixture.
    assert rates["total"] == 30
    assert (rates["exact"], rates["total"], rates["within_one"]) == EXPECTED_RATES[
        language
    ]


def test_fast_index_values_match_for_cases_without_overlay(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    engine_matches: dict[tuple[str, str], int] = {}
    for language in LANGUAGES:
        fixture = load_fixture(language)
        path = repo / f"fixture.{EXTENSIONS[language]}"
        path.write_text(fixture["source"])
        parsed = extract_file(str(path), fixture["source"], language)
        fast = {
            item.name: item.cognitive for item in function_complexities(parsed.entities)
        }
        grade = {
            item.name: item.cognitive
            for item in score_grade_complexities(
                parsed.entities,
                source=fixture["source"],
                language=language,
                path=str(path),
            )
        }
        overlay_names = overlay_case_names(language, fixture)
        for item in fixture["functions"]:
            name = item["name"]
            if name in overlay_names:
                # A declared case that no longer differs from the engine would
                # mean the overlay silently stopped applying.
                assert grade[name] != fast[name]
                continue
            assert grade[name] == fast[name]
            engine_matches[(language, name)] = fast[name]

    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))

    class Provider:
        def extract(self, path: Path, source: str, language: str) -> ExtractOutput:
            return extract_file(str(path), source, language)

    summary = build(repo, Provider())
    with sqlite3.connect(summary.db_path) as connection:
        indexed = {
            (path.rsplit(".", 1)[-1], name): value
            for path, name, value in connection.execute(
                "SELECT files.path, function_metrics.name, function_metrics.cognitive "
                "FROM function_metrics JOIN files ON files.id = "
                "function_metrics.file_id"
            )
        }
    language_for_ext = {
        extension: language for language, extension in EXTENSIONS.items()
    }
    indexed_by_language = {
        (language_for_ext[extension], name): value
        for (extension, name), value in indexed.items()
        if extension in language_for_ext
    }
    for key, value in engine_matches.items():
        assert indexed_by_language[key] == value


@pytest.mark.parametrize("language", LANGUAGES)
def test_hand_derived_values_reach_the_plan_target(language):
    rates = measure_fidelity(language)
    assert cast("float", rates["exact_rate"]) >= 0.95


def test_recursion_overlay_adds_one_without_mutating_fast_engine():
    fixture = load_fixture("java")
    entity_output = extract_file("fixture.java", fixture["source"], "java")
    fast = function_complexities(entity_output.entities)
    grade = score_grade_complexities(
        entity_output.entities,
        source=fixture["source"],
        language="java",
        path="fixture.java",
    )
    fast_recursive = next(item for item in fast if item.name == "c18_recursive_call")
    grade_recursive = next(item for item in grade if item.name == "c18_recursive_call")

    assert fast_recursive.cognitive == 1
    assert grade_recursive.cognitive == 2


def test_java_else_loop_overlay_matches_hand_derived_sonar_value():
    fixture = load_fixture("java")
    parsed = extract_file("fixture.java", fixture["source"], "java")
    fast = function_complexities(parsed.entities)
    grade = score_grade_complexities(
        parsed.entities,
        source=fixture["source"],
        language="java",
        path="fixture.java",
    )
    fast_value = next(item.cognitive for item in fast if item.name == "c29_else_loop")
    grade_value = next(item.cognitive for item in grade if item.name == "c29_else_loop")

    assert fast_value == 5
    assert grade_value == 4


def test_java_else_if_loop_is_not_adjusted_by_else_block_overlay():
    source = (
        "class A { boolean decide(boolean a, boolean b, boolean c) { if (a) "
        "return true; else if (b) { while (c) { break; } } return false; } }"
    )
    parsed = extract_file("else_if_loop.java", source, "java")
    fast = function_complexities(parsed.entities)
    grade = score_grade_complexities(
        parsed.entities,
        source=source,
        language="java",
        path="else_if_loop.java",
    )

    # Sonar counts if +1 and else-if +1; the loop in the else-if body adds
    # 1 structural + 2 nesting. This path is not the direct else-block case.
    assert [(item.name, item.cognitive) for item in fast] == [("decide", 5)]
    assert [(item.name, item.cognitive) for item in grade] == [("decide", 5)]


def test_java_overlay_adjusts_each_direct_else_loop_in_one_function():
    source = (
        "class A { boolean decide(boolean a, boolean b, boolean c, boolean d) { "
        "if (a) return true; else { while (b) { break; } } if (c) return true; "
        "else { while (d) { break; } } return false; } }"
    )
    parsed = extract_file("two_else_loops.java", source, "java")
    fast = function_complexities(parsed.entities)
    grade = score_grade_complexities(
        parsed.entities,
        source=source,
        language="java",
        path="two_else_loops.java",
    )

    # Each direct if/else/loop group derives to 4, so the function totals 8.
    assert [(item.name, item.cognitive) for item in fast] == [("decide", 10)]
    assert [(item.name, item.cognitive) for item in grade] == [("decide", 8)]


def test_recursion_overlay_ignores_a_qualified_same_name_call():
    source = (
        "class A { boolean decide(boolean a, A other) { if (a) return true; "
        "return other.decide(a); } }"
    )
    parsed = extract_file("qualified.java", source, "java")
    fast = function_complexities(parsed.entities)
    grade = score_grade_complexities(
        parsed.entities,
        source=source,
        language="java",
        path="qualified.java",
    )

    assert [(item.name, item.cognitive) for item in fast] == [("decide", 1)]
    assert [(item.name, item.cognitive) for item in grade] == [("decide", 1)]


def test_cpp_lambda_boundary_overlay_adds_nesting_to_enclosing_functions():
    fixture = load_fixture("cpp")
    parsed = extract_file("fixture.cpp", fixture["source"], "cpp")
    fast = function_complexities(parsed.entities)
    grade = score_grade_complexities(
        parsed.entities, source=fixture["source"], language="cpp", path="fixture.cpp"
    )
    fast_values = {item.name: item.cognitive for item in fast}
    grade_values = {item.name: item.cognitive for item in grade}

    assert fast_values["c21_lambda_decision"] == 1
    assert fast_values["c22_if_lambda_decision"] == 3
    assert fast_values["c23_nested_callable"] == 1
    assert grade_values["c21_lambda_decision"] == 2
    assert grade_values["c22_if_lambda_decision"] == 4
    assert grade_values["c23_nested_callable"] == 2


def test_go_repeated_error_checks_follow_sonargo_guard_exemption():
    fixture = load_fixture("go")
    parsed = extract_file("fixture.go", fixture["source"], "go")
    fast = function_complexities(parsed.entities)
    grade = score_grade_complexities(
        parsed.entities, source=fixture["source"], language="go", path="fixture.go"
    )
    fast_check = next(item for item in fast if item.name == "c27_language_idiom")
    grade_check = next(item for item in grade if item.name == "c27_language_idiom")
    expected = next(
        item for item in fixture["functions"] if item["name"] == "c27_language_idiom"
    )

    # SonarGo exempts `if err != nil` guards, so the recorded Sonar value is 0
    # while this engine counts each guard. That difference is documented, not
    # tuned away by the overlay.
    assert expected["expected"] == 0
    assert fast_check.cognitive == 3
    assert grade_check.cognitive == 3
    assert not expected.get("overlay", False)


def test_score_grade_is_deterministic_and_distinguishes_same_name_owners():
    source = (
        "class A { boolean decide(boolean a) { if (a) return true; return false; } }\n"
        "class B { boolean decide(boolean a) { if (a) { if (a) return true; } "
        "return false; } }"
    )
    entities = extract_file("owners.java", source, "java").entities

    first = score_grade_complexities(
        entities, source=source, language="java", path="owners.java"
    )
    second = score_grade_complexities(
        entities, source=source, language="java", path="owners.java"
    )
    assert [(item.owner_type, item.name, item.cognitive) for item in first] == [
        (item.owner_type, item.name, item.cognitive) for item in second
    ]
    assert {(item.owner_type, item.cognitive) for item in first} == {("A", 1), ("B", 3)}


def test_test_callable_is_included_by_score_grade_re_marking():
    source = (
        "def test_decision(flag):\n    if flag:\n        return True\n"
        "    return False\n"
    )
    entities = [
        replace(entity, is_test=True)
        for entity in extract_file("test_quality.py", source, "python").entities
    ]

    assert function_complexities(entities) == []
    assert [
        (item.name, item.cognitive) for item in score_grade_complexities(entities)
    ] == [("test_decision", 1)]
