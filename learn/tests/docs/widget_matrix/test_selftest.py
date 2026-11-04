"""Self-test: the audit must catch planted defects (pure checks and browser)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from . import audit, checks
from .cells import MODES, WIDTHS, all_cells, families_in, scope_for
from .colors import contrast_ratio, parse_color, ratio_over
from .driver import tab_walk
from .rendered import components_in, not_rendered

WHITE, BLACK = (255.0, 255.0, 255.0, 1.0), (0.0, 0.0, 0.0, 1.0)
GREY_119 = parse_color("rgb(119, 119, 119)")
GREY_118 = parse_color("rgb(118, 118, 118)")


def empty_snapshot(**over: Any) -> dict[str, Any]:
    doc = {"scrollWidth": 375, "clientWidth": 375, "lang": "en", "title": "t"}
    base: dict[str, Any] = {
        "doc": doc,
        "controls": [],
        "texts": [],
        "nontext": [],
        "selected": [],
        "bordersLost": [],
        "wide": [],
        "clipped": [],
        "dupIds": [],
        "imagesWithoutAlt": [],
        "aria": [],
        "badRefs": [],
        "series": [],
        "richRoots": [],
        "charWrap": [],
        "splitDates": [],
        "pinOverlap": [],
    }
    return base | over


def control(w: float = 48, h: float = 48, **over: Any) -> dict[str, Any]:
    base = {
        "sel": "button",
        "role": "button",
        "name": "Send",
        "groupName": "",
        "inline": False,
        "target": {"x": 0, "y": 0, "w": w, "h": h},
    }
    return base | over


def stop(**over: Any) -> dict[str, Any]:
    base = {
        "sel": "button",
        "outline": {"style": "solid", "width": 2, "color": "rgb(0, 0, 0)"},
        "shadowWidth": 0,
        "ringColor": "rgb(0, 0, 0)",
        "clipped": False,
        "obscuredBy": "",
        "inView": True,
        "insideBgs": [],
        "outsideBgs": [],
    }
    return base | over


def test_selftest_contrast_maths() -> None:
    assert contrast_ratio(BLACK, WHITE) == pytest.approx(21.0)
    assert contrast_ratio(GREY_119, WHITE) < 4.5  # type: ignore[arg-type]
    assert contrast_ratio(GREY_118, WHITE) >= 4.5  # type: ignore[arg-type]


def test_selftest_alpha_is_composited_over_backdrop() -> None:
    translucent = "rgba(0, 0, 0, 0.5)"
    assert ratio_over(translucent, [], "light") == pytest.approx(3.95, abs=0.05)
    assert ratio_over(translucent, ["rgb(0, 0, 0)"], "light") == pytest.approx(1.0)
    assert ratio_over("color(srgb 0 0 0 / 0.5)", [], "light") is not None
    assert ratio_over("oklch(0.5 0.1 20)", [], "light") is None


def test_selftest_text_contrast_check() -> None:
    low = {
        "sel": "p",
        "text": "x",
        "fg": "rgb(187, 187, 187)",
        "bgs": [],
        "unverifiable": False,
        "opacity": 1,
        "large": False,
    }
    assert checks.check_text_contrast(empty_snapshot(texts=[low]), "light")
    large = low | {"fg": "rgb(140, 140, 140)", "large": True}
    assert not checks.check_text_contrast(empty_snapshot(texts=[large]), "light")


def test_selftest_non_text_contrast_check() -> None:
    faint = {
        "sel": "input",
        "kind": "border",
        "color": "rgb(208, 208, 216)",
        "bgs": [],
        "unverifiable": False,
    }
    assert checks.check_non_text_contrast(empty_snapshot(nontext=[faint]), "light")
    strong = faint | {"color": "rgb(100, 100, 110)"}
    assert not checks.check_non_text_contrast(empty_snapshot(nontext=[strong]), "light")


def test_selftest_target_size_and_overlap() -> None:
    assert checks.check_target_sizes(empty_snapshot(controls=[control(30, 30)]))
    assert not checks.check_target_sizes(empty_snapshot(controls=[control()]))
    prose = control(30, 26, inline=True)
    assert not checks.check_target_sizes(empty_snapshot(controls=[prose]))
    shifted = control(sel="b2") | {"target": {"x": 20, "y": 0, "w": 48, "h": 48}}
    assert checks.check_target_overlap(empty_snapshot(controls=[control(), shifted]))
    apart = control(sel="b2") | {"target": {"x": 60, "y": 0, "w": 48, "h": 48}}
    assert not checks.check_target_overlap(empty_snapshot(controls=[control(), apart]))


def test_selftest_overflow_check() -> None:
    doc = {"scrollWidth": 775, "clientWidth": 375, "lang": "en", "title": "t"}
    assert checks.check_overflow(empty_snapshot(doc=doc))
    child = empty_snapshot(wide=[{"sel": "div", "width": 600, "container": 200}])
    assert checks.check_overflow(child)
    assert not checks.check_overflow(empty_snapshot())


def test_selftest_name_rules() -> None:
    unnamed = empty_snapshot(controls=[control(role="textbox", name="")])
    assert checks.check_names(unnamed)
    loose = empty_snapshot(controls=[control(role="radio", groupName="")])
    assert any("radio-group" in p for p in checks.check_names(loose))
    dup = empty_snapshot(dupIds=["a"], imagesWithoutAlt=["img"])
    assert len(checks.check_names(dup)) == 2
    bad = empty_snapshot(aria=[{"sel": "x", "attr": "aria-bogus", "value": "1"}])
    assert checks.check_names(bad)
    doc = {"scrollWidth": 1, "clientWidth": 1, "lang": "", "title": "t"}
    assert any("lang" in p for p in checks.check_names(empty_snapshot(doc=doc)))
    assert not checks.check_names(empty_snapshot(controls=[control()]))


def test_selftest_focus_rules() -> None:
    assert not checks.check_focus([stop()], "light")
    removed = {"style": "none", "width": 0, "color": "rgb(0, 0, 0)"}
    no_ring = checks.check_focus([stop(outline=removed)], "light")
    assert any("focus-visible" in p for p in no_ring)
    assert not checks.check_focus([stop(shadowWidth=3, outline=removed)], "light")
    pale = stop(ringColor="rgb(230, 230, 230)")
    assert any("focus-contrast" in p for p in checks.check_focus([pale], "light"))
    assert checks.check_focus([stop(clipped=True)], "light")
    assert checks.check_focus([stop(obscuredBy="header")], "light")
    assert checks.check_focus([stop(inView=False)], "light")
    assert not checks.check_focus([pale], "light", forced=True)


def test_selftest_selection_series_and_fallback() -> None:
    fill = {"sel": "label", "borderWidth": 1, "glyph": False}
    assert checks.check_selection(empty_snapshot(selected=[fill]))
    two_px = fill | {"borderWidth": 2}
    assert not checks.check_selection(empty_snapshot(selected=[two_px]))
    assert not checks.check_selection(empty_snapshot(selected=[fill | {"glyph": True}]))
    bare = {"label": "", "marker": "", "dash": "", "pattern": ""}
    same = [bare | {"id": "a"}, bare | {"id": "b"}]
    assert checks.check_series(same)
    assert not checks.check_series([s | {"label": s["id"]} for s in same])
    root = {"sel": ".vb", "hasTable": False, "hasAlt": False}
    assert len(checks.check_nojs_fallback([root], "rich-chart")) == 2
    assert len(checks.check_nojs_fallback([root], "rich-diagram")) == 1


def test_selftest_mode_selection() -> None:
    snap = empty_snapshot(clipped=[{"sel": "pre"}])
    args = {"scheme": "light", "family": "choice"}
    forced = checks.run_checks(snap, [], mode="forced-colors", **args)
    printed = checks.run_checks(snap, [], mode="print", **args)
    assert not forced
    assert printed == ["print-clipped: pre cuts off content"]


def test_selftest_cells_cover_every_axis() -> None:
    cells = all_cells()
    per_family = [c for c in cells if c.family == "choice" and c.fixture == "normal.md"]
    assert len(per_family) == len(WIDTHS) * 2 * len(MODES)
    assert {c.family for c in cells} >= {
        "chrome",
        "choice",
        "form",
        "ranking",
        "slider",
    }
    assert len({c.id for c in cells}) == len(cells)
    assert families_in("rich-chart-stress.md") == ("rich-chart",)
    assert scope_for("chrome")["outside"] == ".vb"


def test_selftest_plain_code_fixture_is_not_rendered() -> None:
    text = '# P\n\n```ui\nc = choice(question: "q", options: ["a"])\n```\n'
    assert components_in(text) == ["choice"]
    as_code = {"roots": [], "code": ['c = choice(question: "q", options: ["a"])']}
    assert len(not_rendered(text, as_code)) == 3
    rendered = {"roots": [["vb", "choice"]], "code": []}
    assert not not_rendered(text, rendered)
    assert not_rendered(text, {"roots": [["vb", "form"]], "code": []})


def test_selftest_real_fixtures_name_every_widget() -> None:
    from .cells import FIXTURES

    for name in ("normal.md", "stress.md"):
        names = set(components_in((FIXTURES / name).read_text(encoding="utf-8")))
        assert names >= {"choice", "form", "ranking", "slider", "decision", "comment"}


PLANTED = """<!doctype html><html lang=en><head><title>planted</title></head>
<body style="margin:0"><main style="width:300px;background:#fff">
<button id=small style="width:30px;height:30px">x</button>
<p style="color:#bbb">pale text</p>
<div style="width:200px"><div style="width:600px;height:10px"></div></div>
<input id=unnamed type=text>
<button id=noring style="outline:none;width:60px;height:60px">Go</button>
</main></body></html>"""
NOBODY = {"inside": None, "outside": ".nothing"}


@pytest.fixture
def planted(matrix_browser: Any) -> Iterator[Any]:
    context = matrix_browser.new_context(viewport={"width": 375, "height": 800})
    page = context.new_page()
    page.set_content(PLANTED)
    yield page
    context.close()


@pytest.mark.slow
def test_selftest_browser_audit_catches_planted_defects(planted: Any) -> None:
    snap = planted.evaluate(audit.COLLECT_JS, NOBODY)
    stops = tab_walk(planted, NOBODY)
    found = checks.run_checks(
        snap, stops, scheme="light", mode="default", family="chrome"
    )
    kinds = {p.split(":")[0] for p in found}
    wanted = {"target-size", "text-contrast", "overflow", "name", "focus-visible"}
    assert wanted <= kinds, f"missing {wanted - kinds}: {found}"


def test_selftest_char_wrap() -> None:
    crushed = {"sel": "th", "text": "status", "length": 6, "lines": 3}
    assert checks.check_no_char_wrap(empty_snapshot(charWrap=[crushed]))
    fine = {"sel": "td", "text": "a long sentence", "length": 15, "lines": 3}
    assert not checks.check_no_char_wrap(empty_snapshot(charWrap=[fine]))
    assert not checks.check_no_char_wrap(empty_snapshot())


def test_selftest_char_wrap_skips_hidden_and_whole_words() -> None:
    js = audit.COLLECT_JS
    assert "srOnly" in js and "inset(50%" in js
    assert "rect(0px,0px,0px,0px)" in js and "brokenWord" in js
    assert "lines > 1" in js


def test_selftest_char_wrap_covers_ranking_and_header_text() -> None:
    js = audit.COLLECT_JS
    assert ".ranking-text" in js and ".choice-label" in js and ".vd-hdr-item" in js


def test_selftest_split_date_and_pin_overlap() -> None:
    date = {"sel": ".vd-hdr-value", "text": "2026-11-04"}
    assert checks.check_no_split_dates(empty_snapshot(splitDates=[date]))
    assert not checks.check_no_split_dates(empty_snapshot())
    pin = {"sel": ".vd-annotated-pin", "text": "return x"}
    assert checks.check_no_pin_overlap(empty_snapshot(pinOverlap=[pin]))
    assert not checks.check_no_pin_overlap(empty_snapshot())
    assert "splitDates" in audit.COLLECT_JS and "pinOverlap" in audit.COLLECT_JS
