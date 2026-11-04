"""Slider redesign: stylesheet rules, markup, and fill and readout in a browser."""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.serve import PageServer

from .test_inputs_ordered import _open, shared_page, site  # noqa: F401

PAGES = Path(str(files("varde_learn.docs.pages")))
CSS = re.sub(
    r"/\*.*?\*/",
    "",
    (PAGES / "static" / "css" / "25-slider.css").read_text(),
    flags=re.DOTALL,
)
PHYSICAL = re.compile(
    r"\b(?:margin|padding|border)-(?:left|right|top|bottom)\b"
    r"|(?<![\w-])(?:left|right|top|bottom|width|height|min-width|min-height)\s*:"
)


def _render(**props: Any) -> str:
    data = {"label": "L", "min": 0, "max": 10, "step": 1, **props}
    return COMPONENTS["slider"].render(data, "w")


def test_hit_area_is_44px_and_thumb_is_larger_than_the_track() -> None:
    assert "min-block-size: var(--vd-control-height)" in CSS
    assert "--slider-thumb: 1.75rem" in CSS and "--slider-track: 0.625rem" in CSS


def test_focus_ring_is_the_shared_field_ring_and_nothing_hides_overflow() -> None:
    assert "button:focus" not in CSS
    assert ".slider-input:focus-visible { outline: none; }" in CSS
    assert (
        ".slider-input:focus-visible::-webkit-slider-thumb { outline: 2px solid" in CSS
    )
    assert ".slider-input:focus-visible::-moz-range-thumb { outline: 2px solid" in CSS
    assert "overflow:" not in CSS.replace("overflow-wrap", "")
    assert PHYSICAL.findall(CSS) == []


def test_track_fill_rtl_and_forced_colors_are_styled() -> None:
    for needle in (
        "var(--vd-fill",
        ":dir(rtl)",
        "::-moz-range-progress",
        "forced-colors: active",
        "CanvasText",
        "tabular-nums",
    ):
        assert needle in CSS, needle


def test_markup_has_ends_in_dom_order_and_numeric_defaults() -> None:
    out = _render(labels=["Low", "High"])
    assert out.index("Low") < out.index("High") and 'class="slider-ends"' in out
    plain = _render(min=-5, max=5)
    assert ">-5<" in plain and ">5<" in plain  # unlabelled ends show the numbers
    assert 'aria-valuetext="Not chosen yet"' in out
    assert "style=" not in out and "<script" not in out


def test_ticks_only_when_at_most_twenty_steps() -> None:
    assert _render(max=10, step=2).count("<span></span>") == 6
    assert _render(max=20).count("<span></span>") == 21
    assert "slider-ticks" not in _render(max=21)
    assert "slider-ticks" not in _render(max=1, step=0.3)


@pytest.mark.slow
def test_browser_fill_readout_valuetext_and_csp(
    shared_page: Any,  # noqa: F811
    site: tuple[PageServer, Path],  # noqa: F811
) -> None:
    server, _doc = site
    page = shared_page
    problems: list[str] = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    _open(page, server)
    page.wait_for_selector(".slider[data-hydrated]")
    conf = page.locator(".slider", has=page.locator("[data-item='conf']"))
    field = conf.locator(".slider-input")
    assert field.get_attribute("aria-valuetext") == "Not chosen yet"
    field.focus()
    page.keyboard.press("End")
    assert field.get_attribute("aria-valuetext") is None
    assert conf.locator(".slider-value").inner_text() == "10"
    fill = field.evaluate("e => e.style.getPropertyValue('--vd-fill')")
    assert float(fill) == 1.0
    assert not [p for p in problems if "Content Security Policy" in p]
