import re

import pytest
from varde_code.model import Entity, EntityKind, ExtractOutput, Span
from varde_code.rules.model import Rule, RuleKind, Severity
from varde_code.rules.model import TestCase as RuleTestCase
from varde_code.rules.test_runner import (
    _compare_rows,
    run_pattern_rule_tests,
    run_sql_rule_tests,
)


def pattern_rule(pattern="console.log($MSG)", **kwargs):
    return Rule(
        "no-console-log",
        RuleKind.PATTERN,
        Severity.WARNING,
        "no console.log",
        pattern=pattern,
        languages=["javascript"],
        **kwargs,
    )


def case(name, **kwargs):
    return RuleTestCase(name=name, **kwargs)


def test_valid_nonmatching_case_passes_and_serializes_rust_field_names():
    result = run_pattern_rule_tests(
        pattern_rule(test=[case("clean", valid=['console.info("hi");'])])
    )[0]
    assert result.passed
    assert result.to_dict() == {
        "rule_id": "no-console-log",
        "test_name": "clean",
        "pass": True,
    }


def test_valid_matching_case_fails_with_match_count_detail():
    result = run_pattern_rule_tests(
        pattern_rule(test=[case("clean", valid=['console.log("oops");'])])
    )[0]
    assert not result.passed
    assert 'snippet: console.log("oops");' in (result.detail or "")
    assert "expected match count: 0" in (result.detail or "")
    assert "actual match count: 1" in (result.detail or "")


def test_invalid_matching_case_passes_and_zero_match_fails():
    passed = run_pattern_rule_tests(
        pattern_rule(test=[case("bad", invalid=['console.log("bad");'])])
    )[0]
    failed = run_pattern_rule_tests(
        pattern_rule(test=[case("bad", invalid=['console.info("clean");'])])
    )[0]
    assert passed.passed
    assert not failed.passed
    assert "expected match count: >=1" in (failed.detail or "")


def test_invalid_pattern_reports_evaluation_failure():
    result = run_pattern_rule_tests(
        pattern_rule("const (", test=[case("invalid", valid=["const answer = 42;"])])
    )[0]
    assert not result.passed
    assert "failed to evaluate" in (result.detail or "")


def test_pattern_snippet_propagates_unexpected_matcher_errors(monkeypatch):
    import varde_code.rules.test_runner as runner

    def fail_unexpectedly(*args):
        raise RuntimeError("matcher defect")

    monkeypatch.setattr(runner, "_match_source", fail_unexpectedly)
    with pytest.raises(RuntimeError, match="matcher defect"):
        run_pattern_rule_tests(
            pattern_rule(test=[case("unexpected", valid=["console.log(1);"])])
        )


def test_rewrite_fixture_uses_captured_source_text():
    rule = pattern_rule(
        rewrite="console.info($MSG)",
        test=[
            case("rewrite", expect_rewrite={'console.log("hi");': 'console.info("hi")'})
        ],
    )
    assert run_pattern_rule_tests(rule)[0].passed


def test_rewrite_mismatch_shows_expected_and_actual():
    rule = pattern_rule(
        rewrite="console.info($MSG)",
        test=[
            case("rewrite", expect_rewrite={'console.log("hi");': 'console.warn("hi")'})
        ],
    )
    result = run_pattern_rule_tests(rule)[0]
    assert not result.passed
    assert 'expected output: console.warn("hi")' in (result.detail or "")
    assert 'actual output: console.info("hi")' in (result.detail or "")


def test_rewrite_without_template_and_nonmatching_rewrite_are_errors():
    missing = run_pattern_rule_tests(
        pattern_rule(test=[case("rewrite", expect_rewrite={"foo()": "bar()"})])
    )[0]
    no_match = run_pattern_rule_tests(
        pattern_rule(
            rewrite="bar()", test=[case("rewrite", expect_rewrite={"foo()": "bar()"})]
        )
    )[0]
    assert "no `rewrite` field" in (missing.detail or "")
    assert "did not match" in (no_match.detail or "")


def test_pattern_runner_covers_cases_and_ignores_other_rule_kinds():
    rule = pattern_rule(
        test=[
            case("valid", valid=["console.info(1);"]),
            case("invalid", invalid=["console.log(1);"]),
        ]
    )
    assert [item.test_name for item in run_pattern_rule_tests(rule)] == [
        "valid",
        "invalid",
    ]
    sql_rule = Rule("sql", RuleKind.SQL, Severity.WARNING, "", test=rule.test)
    assert run_pattern_rule_tests(sql_rule) == []
    assert run_pattern_rule_tests(pattern_rule(test=None)) == []


class FixtureProvider:
    def extract(self, path, source, language):
        entities = []
        for match in re.finditer(r"fn (f\d+)\(\) \{\}", source):
            start, end = match.span()
            line = source.count("\n", 0, start) + 1
            col = start - (source.rfind("\n", 0, start) + 1)
            entities.append(
                Entity(
                    EntityKind.FUNCTION,
                    match.group(1),
                    1,
                    Span(start, end, line, col, line, col + end - start),
                )
            )
        return ExtractOutput(entities=entities)


def sql_rule(test, query=None, rule_id="functions"):
    return Rule(
        rule_id,
        RuleKind.SQL,
        Severity.WARNING,
        "found",
        query=query
        or (
            "SELECT 'lib.rs' AS file, entities.start_line AS line "
            "FROM entities WHERE entities.kind = 0"
        ),
        test=[test],
    )


def fixture(count):
    return {"lib.rs": "".join(f"fn f{i}() {{}}\n" for i in range(count))}


def expected(*lines):
    return [{"file": "lib.rs", "line": line} for line in lines]


def sql_case(name, count=2, rows=None, **kwargs):
    return case(
        name,
        fixture=fixture(count),
        expect_rows=expected(*rows) if rows is not None else [],
        **kwargs,
    )


def test_sql_fixture_query_compares_rows_order_independently():
    result = run_sql_rule_tests(
        sql_rule(sql_case("rows", rows=[2, 1])), FixtureProvider()
    )[0]
    assert result.passed, result.detail
    assert result.rule_id == "functions"


def test_sql_row_comparison_reports_extra_missing_and_unknown_columns():
    extra = _compare_rows(expected(1), expected(1, 2))
    missing = _compare_rows(expected(1, 2, 3), expected(1, 2))
    malformed = _compare_rows(
        [{"file": "lib.rs", "line": 1, "bogus": "x"}], expected(1)
    )
    assert "unexpected extra actual rows" in (extra or "")
    assert "missing expected rows" in (missing or "")
    assert "bogus" in (malformed or "") and "not present" in (malformed or "")


def test_sql_fixture_reports_missing_inputs_and_invalid_queries():
    provider = FixtureProvider()
    no_fixture = run_sql_rule_tests(
        sql_rule(case("fixture", expect_rows=[])), provider
    )[0]
    no_rows = run_sql_rule_tests(sql_rule(case("rows", fixture=fixture(1))), provider)[
        0
    ]
    invalid = run_sql_rule_tests(
        sql_rule(sql_case("sql", rows=[]), query="SELECT FROM"), provider
    )[0]
    assert "missing its `fixture`" in (no_fixture.detail or "")
    assert "missing its `expect_rows`" in (no_rows.detail or "")
    assert not invalid.passed and invalid.detail


def test_sql_runner_ignores_non_sql_rules_and_repeat_runs_do_not_collide():
    provider = FixtureProvider()
    rule = sql_rule(sql_case("repeat", count=1, rows=[1]))
    assert run_sql_rule_tests(rule, provider)[0].passed
    assert run_sql_rule_tests(rule, provider)[0].passed
    pattern = Rule("pattern", RuleKind.PATTERN, Severity.WARNING, "", test=rule.test)
    assert run_sql_rule_tests(pattern, provider) == []
