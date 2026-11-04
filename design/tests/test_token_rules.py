from pathlib import Path

import pytest
from varde_design.settings import Settings
from varde_design.token_rules import (
    check_token_rules,
    derive_base_px,
    normalize_color,
    spacing_offenders,
    without_vars,
)
from varde_design.tokens import extract_tokens, resolved_values

CORE = Settings()
OPINION = Settings(profile="opinion")
TOKENS = ":root{--bg:#fff;--accent:#2457c5;--radius:6px;--s1:4px;--s2:8px}"


def style_of(name: str) -> str:
    path = Path(__file__).parent / "fixtures" / "corpus" / "rules" / name
    return path.read_text(encoding="utf-8").split("<style>")[1].split("</style>")[0]


def run(css: str, settings: Settings = OPINION, tokens: str | None = None):
    found = extract_tokens(css if tokens is None else tokens)
    return check_token_rules(css, "a.css", settings, found)


def ids(css: str, settings: Settings = OPINION, tokens: str | None = None) -> list[str]:
    return [f.id for f in run(css, settings, tokens).findings]


# S7 -------------------------------------------------------------------------


def test_s7_defect_fixture_flags_colours_only() -> None:
    found = run(style_of("S7/defect.html")).findings
    assert [f.id for f in found] == ["S7", "S7"]
    assert {f.snippet for f in found} == {"background: #ff6a00", "color: #102030"}
    assert all(f.severity == "warn" and f.selector == ".panel" for f in found)


def test_s7_clean_twin_has_no_findings() -> None:
    result = run(style_of("S7/clean.html"))
    assert result.findings == [] and result.not_run == []


def test_s7_literal_equal_to_token_value_is_allowed() -> None:
    assert "S7" not in ids(TOKENS + ".a{color:#FFF;border-radius:6px}")


def test_s7_short_and_long_hex_match() -> None:
    assert normalize_color("#FFf") == "#ffffff"
    assert "S7" not in ids(":root{--bg:#ffffff}.a{color:#fff}")


def test_s7_rgb_literal_flagged_and_var_fallback_ignored() -> None:
    assert ids(TOKENS + ".a{color:rgb(1, 2, 3)}") == ["S7"]
    assert ids(TOKENS + ".a{color:var(--accent, #123456)}") == []


def test_s7_resolves_nested_token_value() -> None:
    css = ":root{--base:#102030;--text:var(--base)}.a{color:#102030}"
    assert ids(css) == []


def test_s7_radius_literals_are_not_checked() -> None:
    css = TOKENS + ".a{border-radius:9px}.b{border-radius:6px 7px}"
    assert "S7" not in ids(css)


def test_s7_not_run_without_tokens() -> None:
    result = run(".a{color:#123456}", tokens="")
    assert result.findings == []
    assert result.not_run == ["S7: no tokens found"]


def test_s7_custom_property_declarations_are_not_literals() -> None:
    assert ids(TOKENS + ":root{--extra:#abcdef}") == []


def test_s7_ignored_and_not_in_profile() -> None:
    css = TOKENS + ".a{color:#123456}"
    assert ids(css, Settings(ignore=("S7",))) == []
    assert run(".a{color:#123456}", Settings(ignore=("S7",)), tokens="").not_run == []


# S9 -------------------------------------------------------------------------


def test_s9_defect_fixture_flags_three_declarations() -> None:
    found = run(style_of("S9/defect.html")).findings
    assert [f.id for f in found] == ["S9", "S9", "S9"]
    assert {f.snippet for f in found} == {
        "gap: 18px",
        "padding: 13px",
        "margin: 7px 0",
    }
    assert all(f.severity == "warn" for f in found)


def test_s9_clean_twin_has_no_s9_findings() -> None:
    assert "S9" not in ids(style_of("S9/clean.html"))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2px", []),
        ("3px", ["3px"]),
        ("4px", []),
        ("0", []),
        ("1px 2px", []),
        ("5px 8px 13px", ["5px", "13px"]),
        ("-7px", ["-7px"]),
        ("0.75rem", []),
        ("auto", []),
    ],
)
def test_spacing_offenders_without_scale(value: str, expected: list[str]) -> None:
    assert spacing_offenders(value, None, 4) == expected


def test_s9_runs_without_tokens() -> None:
    assert ids(".a{padding:13px}", OPINION, tokens="") == ["S9"]


def test_s9_explicit_scale_is_strict() -> None:
    settings = Settings(spacing_scale=(4, 8, 16), profile="opinion")
    assert ids(".a{padding:12px}", settings) == ["S9"]
    assert ids(".a{padding:16px}", settings) == []


def test_s9_base_derived_from_spacing_tokens() -> None:
    values = resolved_values(extract_tokens(":root{--space-1:5px;--space-2:10px}"))
    assert derive_base_px(values) == 5
    css = ":root{--space-1:5px;--space-2:10px}.a{padding:15px}.b{padding:8px}"
    assert [f.selector for f in run(css).findings] == [".b"]


def test_s9_non_spacing_property_and_side_properties() -> None:
    assert ids(".a{width:13px;min-height:7px}") == []
    assert (
        ids(".a{padding-left:13px}.b{margin-block:7px}.c{row-gap:9px}", OPINION)
        == ["S9"] * 3
    )


def test_s9_var_references_are_not_literals() -> None:
    assert ids(".a{padding:var(--x, 13px)}", tokens="") == []


def test_s9_ignored() -> None:
    assert ids(".a{padding:13px}", Settings(ignore=("S9",)), tokens="") == []


def test_without_vars_removes_nested_calls() -> None:
    assert without_vars("1px var(--a, calc(1px + 2px)) 3px").split() == ["1px", "3px"]


def test_s7_needs_colour_tokens_to_judge_colours() -> None:
    assert ids(":root{--space-1:4px}\n.a{color:#123456}") == []
    css = ":root{--bg:#ffffff}\n.a{color:#123456}"
    assert ids(css) == ["S7"]


def test_s9_without_a_scale_is_an_opinion_only_convention() -> None:
    css = ".a{padding:13px}"
    assert [f.id for f in run(css, CORE).findings] == []
    assert [f.id for f in run(css, Settings(profile="opinion")).findings] == ["S9"]
