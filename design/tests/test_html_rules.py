import pytest
from varde_design.html_rules import (
    caps_ratio,
    check_html,
    is_placeholder_src,
    kicker_signals,
    kicker_text_ok,
    placeholder_matches,
    tracking_em,
)
from varde_design.settings import Settings

CORE = Settings()
OPINION = Settings(profile="opinion")
HEAD = (
    "<!doctype html>\n<html lang='en'>\n<head><title>T</title>"
    "<meta name='viewport' content='width=device-width'>"
)


def page(body: str, style: str = "") -> str:
    css = f"<style>\n{style}\n</style>" if style else ""
    return f"{HEAD}{css}</head>\n<body>\n{body}\n</body></html>"


def run(text: str, settings: Settings = OPINION) -> list[tuple[str, str]]:
    return [(f.id, f.severity) for f in check_html(text, "a.html", settings)]


def ids(text: str, settings: Settings = OPINION) -> list[str]:
    return [i for i, _ in run(text, settings)]


FOCUS = ":focus-visible { outline: 2px solid blue }"
CLEAN_BODY = "<h1>Title</h1><h2>Sub</h2><p>Hello</p>"


def test_clean_page_has_no_findings() -> None:
    assert run(page(CLEAN_BODY, FOCUS)) == []


# S1 -------------------------------------------------------------------------

KICKER_CSS = ".k { text-transform: uppercase; letter-spacing: 0.1em; font-size: 12px }"
KICKER_BODY = "<p class=k>Our features</p><h2>Big</h2>"


def test_s1_flags_two_signals_in_opinion_profile_with_line() -> None:
    (finding,) = [
        f
        for f in check_html(
            page(KICKER_BODY + "<h1>x</h1>", KICKER_CSS), "a.html", OPINION
        )
        if f.id == "S1"
    ]
    assert (finding.severity, finding.tier, finding.snippet) == (
        "warn",
        "static",
        "Our features",
    )
    assert finding.line == 7


def test_s1_is_off_in_default_profile() -> None:
    assert "S1" not in ids(page(KICKER_BODY, KICKER_CSS), CORE)


def test_s1_inline_style_and_caps_text_count_as_signals() -> None:
    body = "<span style='font-size: 13px'>NEW RELEASE</span><h2>Big</h2>"
    assert "S1" in ids(page(body), OPINION)


def test_s1_one_signal_is_clean_twin() -> None:
    body = "<p style='font-size: 13px'>Our features</p><h2>Big</h2>"
    assert "S1" not in ids(page(body), OPINION)


def test_s1_needs_heading_next_and_not_a_link_or_long_text() -> None:
    css = ".k { text-transform: uppercase; font-size: 12px }"
    assert "S1" not in ids(page("<p class=k>Label</p><p>text</p>", css), OPINION)
    assert "S1" not in ids(page("<a class=k href=/x>Label</a><h2>H</h2>", css), OPINION)
    long = "one two three four five six seven eight"
    assert "S1" not in ids(page(f"<p class=k>{long}</p><h2>H</h2>", css), OPINION)


def test_s1_skips_label_when_heading_is_not_larger() -> None:
    css = ".k { text-transform: uppercase; font-size: 12px } h2 { font-size: 16px }"
    assert "S1" not in ids(page("<p class=k>Label</p><h2>H</h2>", css), OPINION)
    css_big = css.replace("16px", "24px")
    assert "S1" in ids(page("<p class=k>Label</p><h2>H</h2>", css_big), OPINION)


def test_s1_ignore_setting_drops_it() -> None:
    settings = Settings(profile="opinion", ignore=("S1",))
    assert "S1" not in ids(page(KICKER_BODY, KICKER_CSS), settings)


def test_kicker_signal_boundaries() -> None:
    assert kicker_signals("x", {"font-size": "15px"}) == 1
    assert kicker_signals("x", {"font-size": "16px"}) == 0
    assert kicker_signals("x", {"letter-spacing": "0.04em"}) == 1
    assert kicker_signals("x", {"letter-spacing": "0.03em"}) == 0
    assert kicker_signals("x", {"letter-spacing": "1px", "font-size": "20px"}) == 1
    assert kicker_signals("x", {"font-family": "ui-monospace, mono"}) == 1
    assert kicker_signals("x", {"font-variant-caps": "small-caps"}) == 1
    assert kicker_signals("AB", {}) == 1 and kicker_signals("Ab", {}) == 0


def test_kicker_text_and_helpers() -> None:
    assert kicker_text_ok("Our features")
    assert not kicker_text_ok("")
    assert not kicker_text_ok("42%")
    assert not kicker_text_ok("x" * 57)
    assert kicker_text_ok("01 / Intro")
    assert not kicker_text_ok("Q3 2024 12")
    assert caps_ratio("ABc") == pytest.approx(2 / 3) and caps_ratio("123") == 0.0
    assert tracking_em({"letter-spacing": "2px"}, 20.0) == pytest.approx(0.1)
    assert tracking_em({}, None) is None


# S5 -------------------------------------------------------------------------


def test_s5_missing_basics_each_fail_on_html_line() -> None:
    text = "<!doctype html>\n<html>\n<head></head><body><p>x</p></body></html>"
    core = check_html(text, "a.html", CORE)
    messages = sorted(f.message for f in core if f.id == "S5")
    assert messages == [
        "Missing lang on <html>",
        "Missing or empty <title>",
        "Missing viewport meta",
    ]
    assert {(f.severity, f.line) for f in core if f.id == "S5"} == {("warn", 2)}
    opinion = check_html(text, "a.html", OPINION)
    assert "No <h1> on the page" in {f.message for f in opinion if f.id == "S5"}


def test_s5_empty_lang_and_blank_title_count_as_missing() -> None:
    text = "<html lang=' '><head><title> </title></head><body><h1>x</h1></body></html>"
    assert sum(i == "S5" for i in ids(text)) == 3


def test_s5_skipped_heading_is_a_warn_at_the_skipping_heading() -> None:
    found = check_html(
        page("<h1>a</h1><h3>b</h3><h2>c</h2><h4>d</h4>", FOCUS), "a.html", OPINION
    )
    skips = [(f.severity, f.line) for f in found if f.id == "S5"]
    assert skips == [("warn", 7), ("warn", 7)]


def test_s5_heading_steps_down_or_by_one_are_clean() -> None:
    body = "<h1>a</h1><h2>b</h2><h3>c</h3><h1>d</h1><h2>e</h2>"
    assert "S5" not in ids(page(body, FOCUS))


def test_s5_fragment_skips_document_checks_but_checks_skips() -> None:
    assert ids("<h2>a</h2><p>x</p>") == []
    assert ids("<h1>a</h1><h3>b</h3>") == ["S5"]


# S6 -------------------------------------------------------------------------


def test_s6_img_without_alt_fails_and_empty_alt_is_clean() -> None:
    bad = run(page("<h1>t</h1><img src='a.png'>", FOCUS))
    assert bad == [("S6", "fail")]
    assert run(page("<h1>t</h1><img src='a.png' alt=''>", FOCUS)) == []


@pytest.mark.parametrize(
    "src", ["", "#", "about:blank", "https://via.placeholder.com/9"]
)
def test_s6_empty_or_placeholder_src_fails(src: str) -> None:
    body = f"<h1>t</h1><img src='{src}' alt='x'>"
    assert run(page(body, FOCUS)) == [("S6", "fail")]


def test_s6_missing_src_is_flagged_but_srcset_only_is_clean() -> None:
    assert run(page("<h1>t</h1><img alt='x'>", FOCUS)) == [("S6", "fail")]
    assert run(page("<h1>t</h1><img srcset='a.png 2x' alt='x'>", FOCUS)) == []
    assert is_placeholder_src("img/hero.png") is False


# S8 -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "copy",
    [
        "Lorem ipsum dolor",
        "TODO write this",
        "mail me@example.com",
        "Jane Doe, CEO",
        "john smith",
        "Example User",
    ],
)
def test_s8_flags_placeholder_copy_as_warn(copy: str) -> None:
    assert run(page(f"<h1>t</h1><p>{copy}</p>", FOCUS), OPINION) == [("S8", "warn")]
    assert run(page(f"<h1>t</h1><p>{copy}</p>", FOCUS), CORE) == []


def test_s8_line_is_the_matching_line_inside_multiline_text() -> None:
    (finding,) = check_html(
        page("<h1>t</h1><p>fine\n\nTODO later</p>", FOCUS), "a", OPINION
    )
    assert (finding.id, finding.line, finding.snippet) == ("S8", 9, "TODO")


def test_s8_checks_attributes_and_ignores_script() -> None:
    body = "<h1>t</h1><a href='https://example.com/x'>go</a><script>// TODO</script>"
    assert ids(page(body, FOCUS), OPINION) == ["S8"]


def test_s8_clean_twin_and_word_boundaries() -> None:
    assert (
        ids(
            page(
                "<h1>t</h1><p>Todos, counterexample.community, John Smithson</p>", FOCUS
            )
        )
        == []
    )
    assert placeholder_matches("todo") == []


# R7 static ------------------------------------------------------------------


def test_r7_no_focus_visible_with_controls_fails() -> None:
    found = check_html(page("<h1>t</h1><button>Go</button>"), "a.html", OPINION)
    assert [(f.id, f.severity, f.line) for f in found] == [("R7", "warn", 2)]


def test_r7_clean_twins() -> None:
    assert ids(page("<h1>t</h1><button>Go</button>", FOCUS)) == []
    assert ids(page("<h1>t</h1><button class='focus-visible:ring-2'>Go</button>")) == []
    assert ids(page("<h1>t</h1><p>no controls</p>")) == []
    linked = page("<h1>t</h1><button>Go</button>").replace(
        "</head>", "<link rel=stylesheet href=a.css></head>"
    )
    assert ids(linked) == []
    assert ids("<button>fragment</button>") == []


def test_r7_plain_focus_pseudo_does_not_count() -> None:
    assert "R7" in ids(
        page("<h1>t</h1><a href=/>x</a>", "a:focus { outline: 2px solid }")
    )


# Inline CSS bridge ----------------------------------------------------------


def test_style_block_findings_have_document_lines() -> None:
    css = ".h {\n  background: linear-gradient(red, blue);\n  background-clip: text;\n}"
    (finding,) = [
        f for f in check_html(page(CLEAN_BODY, css), "a.html", CORE) if f.id == "S2"
    ]
    assert (finding.line, finding.selector, finding.file) == (6, ".h", "a.html")


def test_style_attribute_runs_css_rules_with_attr_selector() -> None:
    body = "<h1>t</h1><p style='font-size: 8px'>tiny</p>"
    (finding,) = [
        f for f in check_html(page(body, FOCUS), "a.html", CORE) if f.id == "S4"
    ]
    assert finding.selector == "p[style]" and finding.line == 7


# S10 through HTML -----------------------------------------------------------


def test_s10_reduced_motion_missing_warns_once_and_present_is_clean() -> None:
    css = f"{FOCUS}\na {{ transition: opacity 200ms }}\nb {{ transition: color 100ms }}"
    found = [
        f for f in check_html(page(CLEAN_BODY, css), "a", OPINION) if f.id == "S10"
    ]
    assert [(f.severity, f.line) for f in found] == [("warn", 5)]
    ok = css + "\n@media (prefers-reduced-motion: reduce) { a { transition: none } }"
    assert [
        f for f in check_html(page(CLEAN_BODY, ok), "a", OPINION) if f.id == "S10"
    ] == []


def test_s10_ignore_drops_reduced_motion_check() -> None:
    css = f"{FOCUS}\na {{ transition: opacity 200ms }}"
    settings = Settings(ignore=("S10",))
    assert ids(page(CLEAN_BODY, css), settings) == []
