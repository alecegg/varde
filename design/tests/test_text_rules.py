"""R4, R5, R7 (rendered) and R8 over hand-written measurements, then real renders."""

from pathlib import Path

import pytest
from test_render_rules import _metrics
from varde_design.judge import judge, judge_all
from varde_design.probe import NotRun, probe
from varde_design.render_rules import drop_shadowed_r7
from varde_design.report import Finding
from varde_design.settings import Settings

RULES = Path(__file__).parent / "fixtures" / "corpus" / "rules"
OPINION = Settings(profile="opinion")


def _ids(metrics: dict, width: int = 390, settings: Settings | None = None) -> list:
    return [f.id for f in judge(metrics, width, settings or OPINION)]


# R4 -------------------------------------------------------------------------
def _heading(lines: int) -> dict:
    return {"selector": "h1", "text": "Headline", "lines": lines}


def test_r4_is_off_in_the_core_profile() -> None:
    assert _ids(_metrics(headings=[_heading(4)]), settings=Settings()) == []


def test_r4_three_lines_warn_under_the_opinion_profile() -> None:
    found = judge(_metrics(headings=[_heading(3)]), 390, OPINION)
    assert [(f.id, f.severity, f.selector) for f in found] == [("R4", "warn", "h1")]


def test_r4_two_lines_is_the_boundary() -> None:
    assert _ids(_metrics(headings=[_heading(2)]), settings=OPINION) == []
    assert _ids(_metrics(headings=[_heading(1)]), settings=OPINION) == []


# R5 -------------------------------------------------------------------------
def _font(available: bool | None, first: str = "Zephyr Sans Pro") -> dict:
    return {
        "selector": "body",
        "stack": f"'{first}', sans-serif",
        "first": first,
        "count": 3,
        "available": available,
    }


def test_r5_missing_declared_font_warns() -> None:
    found = judge(_metrics(fonts=[_font(False)]), 390, OPINION)
    assert [(f.id, f.severity) for f in found] == [("R5", "warn")]
    assert "Zephyr Sans Pro" in found[0].message


def test_r5_rendered_and_generic_first_families_are_clean() -> None:
    assert _ids(_metrics(fonts=[_font(True, "Georgia")])) == []
    assert _ids(_metrics(fonts=[_font(None, "system-ui")])) == []


# R7 rendered ----------------------------------------------------------------
def _stop(changes: list | None, selector: str = "a") -> dict:
    return {"selector": selector, "tag": "a", "changes": changes}


def _change(fg: str, bg: str = "rgba(255, 255, 255, 1.000)", count: int = 40) -> dict:
    return {"fg": fg, "bg": bg, "count": count}


def _focus(*stops: dict) -> dict:
    return {"stops": list(stops), "capped": False}


BLUE = "rgba(26, 79, 214, 1.000)"  # about 6.5:1 on white
PALE = "rgba(200, 200, 200, 1.000)"  # about 1.7:1


def test_r7_visible_ring_is_clean() -> None:
    metrics = _metrics(focus=_focus(_stop([_change(BLUE)])))
    assert _ids(metrics) == []


def test_r7_pale_ring_fails() -> None:
    found = judge(_metrics(focus=_focus(_stop([_change(PALE)]))), 390, OPINION)
    assert [(f.id, f.severity, f.tier) for f in found] == [("R7", "warn", "rendered")]
    assert "ring 1." in found[0].snippet


def test_r7_no_visible_change_fails() -> None:
    found = judge(_metrics(focus=_focus(_stop([]))), 390, OPINION)
    assert [f.snippet for f in found] == ["no visible focus change"]


def test_r7_boundary_is_2_95() -> None:
    # #959595 on white is above 2.95:1 (clean); #989898 is below it (fails).
    assert (
        _ids(_metrics(focus=_focus(_stop([_change("rgba(149, 149, 149, 1.000)")]))))
        == []
    )
    low = _change("rgba(152, 152, 152, 1.000)")
    assert _ids(_metrics(focus=_focus(_stop([low])))) == ["R7"]


def test_r7_strongest_change_counts_and_unmeasured_stops_are_skipped() -> None:
    mixed = _stop([_change(PALE), _change(BLUE, count=3)])
    assert _ids(_metrics(focus=_focus(mixed, _stop(None)))) == []


def test_r7_repeated_stops_report_once_and_no_walk_is_silent() -> None:
    bad = _stop([])
    assert _ids(_metrics(focus=_focus(bad, bad))) == ["R7"]
    assert _ids(_metrics(focus=None)) == []


def _finding(tier: str) -> Finding:
    return Finding("R7", "fail", tier, "page.html", "m")


def test_static_r7_shadows_the_rendered_walk() -> None:
    both = [_finding("static"), _finding("rendered")]
    assert [f.tier for f in drop_shadowed_r7(both)] == ["static"]
    assert [f.tier for f in drop_shadowed_r7([_finding("rendered")])] == ["rendered"]


# R8 -------------------------------------------------------------------------
def _para(first: int, lines: int = 3, sentences: int = 3) -> dict:
    return {
        "selector": "p",
        "chars": first * lines,
        "sentences": sentences,
        "lines": lines,
        "first_line_chars": first,
    }


def test_r8_long_line_warns_at_the_widest_width_only() -> None:
    metrics = _metrics(paragraphs=[_para(120)], width=1440)
    assert _ids(metrics, 1440) == ["R8"]
    narrow = _metrics(paragraphs=[_para(120)], width=390)
    narrow["widths"].append({**narrow["widths"][0], "width": 1440, "paragraphs": []})
    assert _ids(narrow, 390) == []


def test_r8_upper_boundary_is_max_line_chars() -> None:
    assert _ids(_metrics(paragraphs=[_para(75)])) == []
    assert (
        _ids(_metrics(paragraphs=[_para(76)])) == []
    )  # inside the 15 percent tolerance
    assert _ids(_metrics(paragraphs=[_para(87)])) == ["R8"]
    assert (
        _ids(_metrics(paragraphs=[_para(87)]), settings=Settings(max_line_chars=80))
        == []
    )


def test_r8_lower_boundary_is_45_for_reading_text() -> None:
    assert _ids(_metrics(paragraphs=[_para(45)])) == []
    assert _ids(_metrics(paragraphs=[_para(44)])) == ["R8"]


def test_r8_one_sentence_lede_has_a_floor_of_28() -> None:
    assert _ids(_metrics(paragraphs=[_para(28, sentences=1)])) == []
    assert _ids(_metrics(paragraphs=[_para(27, sentences=1)])) == ["R8"]


def test_r8_single_short_line_is_not_a_measure() -> None:
    assert _ids(_metrics(paragraphs=[_para(12, lines=1)])) == []
    assert _ids(_metrics(paragraphs=[_para(120, lines=1)])) == ["R8"]


def test_r8_message_names_the_measure() -> None:
    found = judge(_metrics(paragraphs=[_para(200)]), 390, OPINION)
    assert "over 200 characters" in found[0].snippet


# Real renders ---------------------------------------------------------------
def _measure(rule: str, kind: str) -> dict:
    result = probe(str(RULES / rule / f"{kind}.html"), (390, 1440))
    assert not isinstance(result, NotRun), result.message()
    return result


def _fixture(rule: str, kind: str, settings: Settings) -> list[tuple[str, int | None]]:
    return [(f.id, f.width) for f in judge_all(_measure(rule, kind), settings)]


@pytest.mark.slow
def test_r4_fixtures() -> None:
    defect = _fixture("R4", "defect", OPINION)
    assert ("R4", 1440) in defect or ("R4", 390) in defect
    assert {rule for rule, _ in defect} == {"R4"}
    assert _fixture("R4", "defect", Settings()) == []
    assert _fixture("R4", "clean", OPINION) == []


@pytest.mark.slow
def test_r5_fixtures() -> None:
    assert _fixture("R5", "defect", Settings()) == [("R5", 390), ("R5", 1440)]
    assert _fixture("R5", "clean", Settings()) == []


@pytest.mark.slow
def test_r7_fixtures() -> None:
    # The defect fixture's bare links are also under 44px at 390 (R3), so filter R7.
    defect = [f for f in _fixture("R7", "defect", OPINION) if f[0] == "R7"]
    assert defect == [("R7", 1440), ("R7", 1440)]
    assert [f for f in _fixture("R7", "clean", OPINION) if f[0] == "R7"] == []


@pytest.mark.slow
def test_r8_defect_fixture_flags_the_widest_width_only() -> None:
    assert _fixture("R8", "defect", Settings()) == [("R8", 1440)]


@pytest.mark.slow
def test_r8_clean_fixture_is_clean() -> None:
    assert _fixture("R8", "clean", Settings()) == []


def _stack_font(stack: str) -> dict:
    return {**_font(False), "stack": stack}


def test_r5_named_or_system_fallback_is_a_designed_stack() -> None:
    for stack in ("Inter, system-ui, sans-serif", "Consolas, Menlo, monospace"):
        assert _ids(_metrics(fonts=[_stack_font(stack)])) == []
    assert _ids(_metrics(fonts=[_stack_font("Inter, sans-serif")])) == ["R5"]
    assert _ids(_metrics(fonts=[_stack_font("Inter")])) == ["R5"]


def test_r8_first_line_within_fifteen_percent_of_the_limit_is_tolerated() -> None:
    assert _ids(_metrics(paragraphs=[_para(83)], width=1440), 1440) == []
    assert _ids(_metrics(paragraphs=[_para(88)], width=1440), 1440) == ["R8"]
