import pytest
from varde_design.css_rules import check_css, is_ui_selector, parse_px
from varde_design.settings import Settings

CORE = Settings()
OPINION = Settings(profile="opinion")


def ids(css: str, settings: Settings = CORE) -> list[str]:
    return [f.id for f in check_css(css, "a.css", settings)]


# parse_px -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("12px", 12.0),
        ("0.75rem", 12.0),
        (" 1.5rem ", 24.0),
        ("1em", None),
        ("var(--x)", None),
        ("12", None),
    ],
)
def test_parse_px(value: str, expected: float | None) -> None:
    assert parse_px(value) == expected


# S2 -------------------------------------------------------------------------

S2_BAD = (
    ".h {\n  background: linear-gradient(90deg, red, blue);\n"
    "  -webkit-background-clip: text;\n  color: transparent;\n}"
)


def test_s2_flags_gradient_text_with_line_and_warn_severity() -> None:
    (finding,) = check_css(S2_BAD, "a.css", CORE)
    assert (finding.id, finding.severity, finding.tier) == ("S2", "warn", "static")
    assert (finding.line, finding.selector) == (3, ".h")
    assert finding.snippet == "-webkit-background-clip: text"


def test_s2_flags_unprefixed_clip_with_background_image() -> None:
    css = ".h { background-image: radial-gradient(red, blue); background-clip: text }"
    assert ids(css) == ["S2"]


def test_s2_clean_twins() -> None:
    clip_only = ".h { background-clip: text; color: red }"
    gradient_only = ".h { background: linear-gradient(red, blue) }"
    solid_clip = ".h { background: red; background-clip: text }"
    padding_clip = (
        ".h { background: linear-gradient(red, blue); background-clip: padding-box }"
    )
    in_comment = (
        "/* .h { background: linear-gradient(red, blue); background-clip: text } */"
    )
    for css in (clip_only, gradient_only, solid_clip, padding_clip, in_comment):
        assert ids(css) == []


def test_s2_clip_and_gradient_on_different_rules_do_not_combine() -> None:
    css = ".a { background: linear-gradient(red, blue) }\n.b { background-clip: text }"
    assert ids(css) == []


# S3 -------------------------------------------------------------------------


def test_s3_is_off_in_core_profile_and_on_in_opinion() -> None:
    css = ".c { border-left: 4px solid #3366ff }"
    assert ids(css, CORE) == []
    (finding,) = check_css(css, "a.css", OPINION)
    assert (finding.id, finding.severity, finding.line) == ("S3", "warn", 1)


def test_s3_square_card_boundary_at_four_px() -> None:
    assert ids(".c { border-left: 3px solid #36f }", OPINION) == []
    assert ids(".c { border-left: 4px solid #36f }", OPINION) == ["S3"]
    assert ids(".c { border-right: 4px solid red }", OPINION) == ["S3"]


def test_s3_rounded_card_boundary_at_two_px() -> None:
    base = ".c { border-radius: 8px; border-left: %s solid #36f }"
    assert ids(base % "1px", OPINION) == []
    assert ids(base % "2px", OPINION) == ["S3"]
    assert ids(".c { border-radius: 50%; border-left: 2px solid #36f }", OPINION) == [
        "S3"
    ]
    assert ids(".c { border-radius: 0; border-left: 2px solid #36f }", OPINION) == []


def test_s3_sees_radius_declared_after_the_border_across_lines() -> None:
    css = ".c {\n  border-left: 2px solid #36f;\n  border-radius: 6px;\n}"
    (finding,) = check_css(css, "a.css", OPINION)
    assert finding.line == 2


def test_s3_neutral_and_non_border_cases_are_clean() -> None:
    for css in (
        ".c { border-left: 4px solid #ccc }",
        ".c { border-left: 4px solid gray }",
        ".c { border-left: 4px solid transparent }",
        ".c { border-left: 4px none #36f }",
        ".c { border-left: none }",
        ".c { border-top: 4px solid #36f }",
        "/* .c { border-left: 4px solid #36f } */",
    ):
        assert ids(css, OPINION) == []


def test_s3_accepts_functional_colors_and_both_sides() -> None:
    css = (
        ".c { border-left: 4px solid rgb(10, 20, 200);"
        " border-right: 5px solid hsl(200 80% 40%) }"
    )
    assert ids(css, OPINION) == ["S3", "S3"]


# S4 -------------------------------------------------------------------------


def test_s4_prose_boundary_at_twelve_px() -> None:
    assert ids("p { font-size: 11px }") == ["S4"]
    assert ids("p { font-size: 11.9px }") == ["S4"]
    assert ids("p { font-size: 12px }") == []
    assert ids("p { font-size: 0.7rem }") == ["S4"]
    assert ids("p { font-size: 0.75rem }") == []


def test_s4_ui_text_uses_its_own_lower_minimum() -> None:
    assert is_ui_selector(".primary-button") and not is_ui_selector(".article p")
    assert ids(".btn { font-size: 11px }") == []
    assert ids(".btn { font-size: 10px }") == ["S4"]
    (finding,) = check_css("input { font-size: 10px }", "a.css", CORE)
    assert "UI" in finding.message and finding.severity == "warn"


def test_s4_honors_settings_thresholds() -> None:
    strict = Settings(min_text_px=14, min_ui_text_px=13)
    assert ids("p { font-size: 13px }", strict) == ["S4"]
    assert ids("button { font-size: 13px }", strict) == []
    assert ids("p { font-size: 13px }", Settings(min_text_px=10)) == []


def test_s4_skips_unresolvable_zero_and_commented_sizes() -> None:
    for css in (
        "p { font-size: var(--small) }",
        "p { font-size: 80% }",
        "p { font-size: 0 }",
        "p { font-size: 1em }",
        "/* p { font-size: 8px } */",
    ):
        assert ids(css) == []


def test_s4_last_declaration_wins() -> None:
    assert ids("p { font-size: 8px; font-size: 14px }") == []
    assert ids("p { font-size: 14px; font-size: 8px }") == ["S4"]


def test_s4_reports_inside_media_query_with_real_line() -> None:
    css = "@media (max-width: 500px) {\n  p {\n    font-size: 9px;\n  }\n}"
    (finding,) = check_css(css, "a.css", CORE)
    assert (finding.line, finding.selector) == (3, "p")


# settings -------------------------------------------------------------------


def test_ignore_setting_drops_a_rule() -> None:
    css = S2_BAD + "\np { font-size: 8px }"
    assert sorted(ids(css)) == ["S2", "S4"]
    assert ids(css, Settings(ignore=("S2",))) == ["S4"]


def test_findings_validate_against_report_schema() -> None:
    from varde_design.report import build_report, checked_block, validate_report

    findings = check_css(S2_BAD + "\np { font-size: 8px }", "a.css", OPINION)
    checked = checked_block(tiers=["static"], widths=[], settings_source="defaults")
    assert validate_report(build_report("check", findings, checked)) == []


def test_s4_class_only_selector_gets_the_ui_minimum() -> None:
    assert ids(".time{font-size:11px}") == []
    assert ids(".time{font-size:10px}") == ["S4"]
    assert ids("p{font-size:11px}") == ["S4"]
    assert ids("main p.lede{font-size:11px}") == ["S4"]
