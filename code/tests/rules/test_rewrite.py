import pytest
from varde_code.rules.rewrite import (
    RewritePlan,
    RewriteStatus,
    RewriteTarget,
    TemplateToken,
    plan_file_rewrites,
    substitute,
    substitute_with_source,
    template_tokens,
)


def single(text):
    return {"kind": "identifier", "text": text}


def spanned(text, start_byte, end_byte):
    return {
        "kind": "identifier",
        "text": text,
        "span": {"start_byte": start_byte, "end_byte": end_byte},
    }


def test_substitutes_single_and_multiple_captures():
    captures = {"MSG": single('"hi"'), "VAL": single('"secret"')}
    assert substitute("console.info($MSG);", captures) == 'console.info("hi");'
    assert substitute("$MSG = $VAL", captures) == '"hi" = "secret"'


def test_variadic_capture_preserves_source_separators():
    source = "f(a,\n  b , c)"
    captures = {"ARGS": [spanned("a", 2, 3), spanned("b", 7, 8), spanned("c", 11, 12)]}
    assert substitute_with_source("g($$$ARGS)", captures, source) == "g(a,\n  b , c)"


@pytest.mark.parametrize(
    "source,nodes",
    [
        ("abcdef", [spanned("a", 2, 1), spanned("b", 3, 4)]),
        ("abcdef", [spanned("a", 0, 1), spanned("b", 5, 99)]),
        ("abcdef", [spanned("a", 0, 4), spanned("b", 3, 5)]),
        ("éx", [spanned("a", 0, 1), spanned("b", 2, 3)]),
    ],
)
def test_malformed_array_spans_fall_back_to_text_only(source, nodes):
    assert substitute_with_source("{$$$BODY}", {"BODY": nodes}, source) == "{ab}"


def test_empty_array_and_array_without_valid_spans():
    assert substitute("f($$$ARGS)", {"ARGS": []}) == "f()"
    assert substitute("f($$$ARGS)", {"ARGS": [single("a"), single("b")]}) == "f(ab)"


def test_literals_unknown_names_and_dollars_are_preserved():
    captures = {"VAR": single("x")}
    assert (
        substitute("before $VAR after — unchanged", captures)
        == "before x after — unchanged"
    )
    assert (
        substitute("$MISSING; cost $5, $$$ tail", captures)
        == "$MISSING; cost $5, $$$ tail"
    )
    assert substitute("$VAR; $VARB", {"VAR": single("yes")}) == "yes; $VARB"


def test_capture_shape_mismatch_degrades_gracefully():
    assert substitute("$ARGS/$$$ARGS", {"ARGS": single("only")}) == "only/only"
    array = {"ARGS": [single("a"), single("b")]}
    assert substitute("$ARGS/$$$ARGS", array) == "ab/ab"


def test_unicode_template_and_capture_content_survive():
    captures = {"MSG": single("héllo — 世界")}
    assert (
        substitute("前$MSG後 — unchanged", captures) == "前héllo — 世界後 — unchanged"
    )


def test_template_tokens_match_token_contract():
    assert list(template_tokens("é$$$ARGS + $A; $AB $$")) == [
        TemplateToken(1, 8, True, "ARGS"),
        TemplateToken(11, 13, False, "A"),
        TemplateToken(15, 18, False, "AB"),
    ]


def target(start, end):
    return RewriteTarget(start, end, f"[{start},{end})")


def test_non_overlapping_and_adjacent_targets_all_apply():
    assert plan_file_rewrites([target(10, 20), target(0, 5), target(5, 10)]) == [
        RewritePlan.APPLY,
        RewritePlan.APPLY,
        RewritePlan.APPLY,
    ]


def test_sorted_overlaps_are_skipped_and_decisions_keep_input_order():
    assert plan_file_rewrites([target(5, 15), target(0, 10), target(2, 4)]) == [
        RewritePlan.SKIPPED_OVERLAP,
        RewritePlan.APPLY,
        RewritePlan.SKIPPED_OVERLAP,
    ]
    assert plan_file_rewrites([target(0, 5), target(0, 5)]) == [
        RewritePlan.APPLY,
        RewritePlan.SKIPPED_OVERLAP,
    ]


def test_rewrite_plans_are_rule_agnostic_and_empty_input_is_empty():
    assert plan_file_rewrites([target(0, 5), target(3, 8), target(9, 12)]) == [
        RewritePlan.APPLY,
        RewritePlan.SKIPPED_OVERLAP,
        RewritePlan.APPLY,
    ]
    assert plan_file_rewrites([]) == []


def test_status_values_use_kebab_case():
    assert [status.value for status in RewriteStatus] == [
        "applied",
        "skipped-dirty",
        "skipped-overlap",
        "skipped-conflict",
    ]
