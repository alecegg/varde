"""R1, R3 and R6 over hand-written measurements, then over real renders (slow)."""

from pathlib import Path
from typing import Any

import pytest
from varde_design.judge import judge, judge_all
from varde_design.probe import NotRun, probe
from varde_design.render_rules import backdrop_colors
from varde_design.settings import Settings

RULES = Path(__file__).parent / "fixtures" / "corpus" / "rules"


def _text(
    color: str = "rgba(0, 0, 0, 1.000)",
    px: float = 16,
    weight: int = 400,
    layers: tuple[str, ...] = ("rgba(255, 255, 255, 1.000)",),
    image: str = "none",
    stops: tuple[str, ...] = (),
) -> dict:
    return {
        "selector": "p",
        "text": "Hello",
        "color": color,
        "font_px": px,
        "weight": weight,
        "font_family": "serif",
        "backdrop": {"layers": list(layers), "image": image, "stops": list(stops)},
    }


def _control(w: float = 44, h: float = 44, inline: bool = False) -> dict:
    return {
        "selector": "button",
        "tag": "button",
        "width": w,
        "height": h,
        "inline": inline,
    }


def _metrics(texts=(), controls=(), errors=(), width: int = 390, **extra: Any) -> dict:
    """Hand-written probe result; extra: fonts, headings, paragraphs, focus."""
    entry: dict[str, Any] = {
        "width": width,
        "doc": {"scroll_width": width, "client_width": width},
        "texts": list(texts),
        "controls": list(controls),
        "errors": list(errors),
        "fonts": [],
        "headings": [],
        "paragraphs": [],
        "focus": None,
        "truncated": None,
        **extra,
    }
    return {"schema": 1, "target": "page.html", "widths": [entry]}


def _ids(metrics: dict, width: int = 390, settings: Settings | None = None) -> list:
    return [f.id for f in judge(metrics, width, settings or Settings())]


# R1 -------------------------------------------------------------------------
# #777 on white is 4.48:1 (inside the 0.05 margin); #767676 is 4.54:1.
GREY_4_48 = "rgba(119, 119, 119, 1.000)"
GREY_4_54 = "rgba(118, 118, 118, 1.000)"


def test_r1_low_contrast_text_fails() -> None:
    findings = judge(_metrics([_text("rgba(170, 170, 170, 1.000)")]), 390, Settings())
    assert [(f.id, f.severity, f.selector) for f in findings] == [("R1", "fail", "p")]
    assert "2.3" in findings[0].message


def test_r1_clean_twin_passes() -> None:
    assert _ids(_metrics([_text("rgba(89, 89, 89, 1.000)")])) == []


def test_r1_margin_below_threshold_is_tolerated() -> None:
    assert _ids(_metrics([_text(GREY_4_48)])) == []
    assert _ids(_metrics([_text("rgba(120, 120, 120, 1.000)")])) == ["R1"]
    assert _ids(_metrics([_text(GREY_4_54)])) == []


def test_r1_large_text_uses_three_to_one() -> None:
    grey = "rgba(143, 143, 143, 1.000)"  # about 3.3:1
    assert _ids(_metrics([_text(grey, px=24)])) == []
    assert _ids(_metrics([_text(grey, px=23.9)])) == ["R1"]


def test_r1_bold_large_text_boundary() -> None:
    grey = "rgba(143, 143, 143, 1.000)"
    assert _ids(_metrics([_text(grey, px=18, weight=700)])) == []
    assert _ids(_metrics([_text(grey, px=18, weight=600)])) == ["R1"]
    assert _ids(_metrics([_text(grey, px=17.9, weight=700)])) == ["R1"]


def test_r1_translucent_text_is_composited_over_the_backdrop() -> None:
    assert _ids(_metrics([_text("rgba(0, 0, 0, 0.300)")])) == ["R1"]
    assert _ids(_metrics([_text("rgba(0, 0, 0, 0.800)")])) == []


def test_r1_translucent_backdrop_is_composited_over_its_parent() -> None:
    layers = ("rgba(0, 0, 0, 0.500)", "rgba(255, 255, 255, 1.000)")
    assert _ids(_metrics([_text("rgba(60, 60, 60, 1.000)", layers=layers)])) == ["R1"]


def test_r1_no_background_falls_back_to_white_canvas() -> None:
    assert _ids(_metrics([_text("rgba(255, 255, 255, 1.000)", layers=())])) == ["R1"]


def test_r1_gradient_fails_only_when_the_best_stop_fails() -> None:
    stops = ("rgba(255, 255, 255, 1.000)", "rgba(40, 40, 40, 1.000)")
    white = _text("rgba(255, 255, 255, 1.000)", image="gradient", stops=stops)
    assert _ids(_metrics([white])) == []
    grey = ("rgba(200, 200, 200, 1.000)", "rgba(180, 180, 180, 1.000)")
    flat = _text("rgba(255, 255, 255, 1.000)", image="gradient", stops=grey)
    assert _ids(_metrics([flat])) == ["R1"]


def test_r1_background_image_and_invisible_text_are_skipped() -> None:
    photo = _text("rgba(255, 255, 255, 1.000)", image="image")
    hidden = _text("rgba(0, 0, 0, 0.000)")
    assert _ids(_metrics([photo, hidden])) == []
    assert backdrop_colors(photo["backdrop"]) is None


# R3 -------------------------------------------------------------------------
def test_r3_small_target_warns_at_mobile_width() -> None:
    findings = judge(_metrics(controls=[_control(24, 24)]), 390, Settings())
    assert [(f.id, f.severity, f.snippet) for f in findings] == [
        ("R3", "warn", "24x24px")
    ]


def test_r3_boundary_is_the_configured_minimum() -> None:
    assert _ids(_metrics(controls=[_control(44, 44)])) == []
    assert _ids(_metrics(controls=[_control(43.6, 44)])) == []
    assert _ids(_metrics(controls=[_control(44, 43)])) == ["R3"]
    assert (
        _ids(_metrics(controls=[_control(60, 30)]), settings=Settings(min_target_px=30))
        == []
    )
    assert _ids(
        _metrics(controls=[_control(60, 30)]), settings=Settings(min_target_px=31)
    ) == ["R3"]


def test_r3_inline_text_links_are_exempt() -> None:
    assert _ids(_metrics(controls=[_control(60, 18, inline=True)])) == []


def test_r3_only_runs_at_mobile_width() -> None:
    metrics = _metrics(controls=[_control(24, 24)], width=1440)
    assert _ids(metrics, 1440) == []
    assert _ids(_metrics(controls=[_control(24, 24)], width=480), 480) == ["R3"]
    assert _ids(_metrics(controls=[_control(24, 24)], width=481), 481) == []


def test_r3_identical_controls_report_once() -> None:
    assert _ids(_metrics(controls=[_control(24, 24), _control(24, 24)])) == ["R3"]


# R6 -------------------------------------------------------------------------
def _error(kind: str = "console", text: str = "boom", url: str = "") -> dict:
    return {"kind": kind, "text": text, "url": url}


def test_r6_console_and_page_errors_fail() -> None:
    errors = [_error(), _error("pageerror", "ReferenceError: x is not defined")]
    findings = judge(_metrics(errors=errors), 390, Settings())
    assert [(f.id, f.severity) for f in findings] == [("R6", "fail"), ("R6", "fail")]
    assert any("ReferenceError" in f.message for f in findings)


def test_r6_no_errors_is_clean() -> None:
    assert _ids(_metrics()) == []


def test_r6_favicon_miss_is_noise() -> None:
    noise = _error(text="Failed to load resource: 404", url="http://x.test/favicon.ico")
    assert _ids(_metrics(errors=[noise])) == []
    real = _error(text="Failed to load resource: 404", url="http://x.test/app.js")
    assert _ids(_metrics(errors=[real])) == ["R6"]


def test_r6_repeated_error_reports_once_per_width() -> None:
    assert _ids(_metrics(errors=[_error(), _error()])) == ["R6"]


# Real renders ---------------------------------------------------------------
def _measure(rule: str, kind: str) -> dict:
    result = probe(str(RULES / rule / f"{kind}.html"), (390, 1440))
    assert not isinstance(result, NotRun), result.message()
    return result


def _fixture_ids(rule: str, kind: str) -> list[tuple[str, int | None]]:
    return [(f.id, f.width) for f in judge_all(_measure(rule, kind), Settings())]


@pytest.mark.slow
def test_r1_fixtures() -> None:
    assert _fixture_ids("R1", "defect") == [("R1", 390), ("R1", 1440)]
    assert _fixture_ids("R1", "clean") == []


@pytest.mark.slow
def test_r3_fixtures_flag_mobile_only() -> None:
    found = _fixture_ids("R3", "defect")
    assert found and {width for _, width in found} == {390}
    assert {rule for rule, _ in found} == {"R3"}
    assert _fixture_ids("R3", "clean") == []


@pytest.mark.slow
def test_r6_fixtures() -> None:
    assert _fixture_ids("R6", "defect") == [
        ("R6", 390),
        ("R6", 390),
        ("R6", 1440),
        ("R6", 1440),
    ]
    assert _fixture_ids("R6", "clean") == []


def test_r6_offline_load_failures_are_noise_but_script_errors_fail() -> None:
    offline = [
        "Failed to load resource: net::ERR_FILE_NOT_FOUND",
        "Failed to load resource: net::ERR_NAME_NOT_RESOLVED",
        "Access to script at 'file:///x/app.js' from origin 'null' has been blocked",
        "Failed to fetch dynamically imported module: file:///x/m.js",
    ]
    assert _ids(_metrics(errors=[_error(text=t) for t in offline])) == []
    real = _error("pageerror", "undefinedFunction is not defined")
    assert _ids(_metrics(errors=[real])) == ["R6"]
    status = _error(
        text="Failed to load resource: the server responded with a status of 500"
    )
    assert _ids(_metrics(errors=[status])) == ["R6"]
