"""Form widget design: stacked fields, hints, grid, error and checkbox styling.

Markup and stylesheet checks run without a browser; the widget matrix
(`widget_matrix -k form`) covers layout, contrast and focus in Chromium.
"""

from __future__ import annotations

import re
from pathlib import Path

from varde_learn.docs.pages.blocks_render.registry import COMPONENTS

PAGES = Path(__file__).resolve().parents[2] / "src/varde_learn/docs/pages"
CSS = (PAGES / "static/css/21-form.css").read_text()
JS = (PAGES / "static/recap.js").read_text()
FIELDS = [
    {"name": "who", "label": "Who", "type": "text", "maxlength": 20, "required": True},
    {"name": "n", "label": "N", "type": "number", "min": 1, "max": 9},
    {"name": "low", "label": "Low", "type": "number", "min": 3},
    {"name": "r", "label": "R", "type": "select", "options": ["a"]},
    {"name": "ok", "label": "OK", "type": "checkbox"},
]


def _render() -> str:
    return COMPONENTS["form"].render({"fields": FIELDS, "title": "T"}, "w")


def test_each_field_is_a_row_with_label_control_and_hint() -> None:
    out = _render()
    assert out.count('class="form-row') == 5
    assert out.count('<label class="form-field">') == 5
    assert (
        '<span class="form-hint" id="form-w-who-hint">Up to 20 characters.</span>'
        in out
    )
    assert 'aria-describedby="form-w-who-hint"' in out
    assert "From 1 to 9." in out and "At least 3." in out
    assert out.count('class="form-hint"') == 3  # select and checkbox have none


def test_fields_sit_in_a_container_grid_and_required_count_is_empty_server_side() -> (
    None
):
    out = _render()
    assert '<div class="form-body"><div class="form-grid">' in out
    assert '<p class="form-remaining" aria-live="polite"></p>' in out
    assert "style=" not in out and "<script" not in out


def test_checkbox_control_comes_before_its_label_text() -> None:
    out = _render()
    box = re.search(r'<div class="form-row form-checkbox">.*?</div>', out, re.DOTALL)
    assert box and box.group(0).index("<input") < box.group(0).index("form-label")


def test_css_uses_container_grid_44px_controls_and_16px_font() -> None:
    assert "container-type: inline-size" in CSS
    assert "@container (min-width: 40rem)" in CSS and "repeat(2," in CSS
    assert "@media (min-width" not in CSS
    assert "var(--vd-control-height)" in CSS and "max(1rem, 16px)" in CSS
    assert "accent-color: var(--vd-accent)" in CSS
    assert "outline: none" not in CSS and "outline:none" not in CSS


def test_invalid_state_is_a_thicker_border_and_the_shared_error_text() -> None:
    assert re.search(r'\[aria-invalid="true"\][^{]*\{[^}]*border-width: 2px', CSS)
    assert ".form-error" in CSS and "var(--vd-error)" in CSS
    assert "button:focus-visible" not in CSS


def test_form_script_tracks_required_fields_and_invalid_controls() -> None:
    start = JS.index("function unfilled")
    form_js = JS[start : JS.index("register('answers'", start)]
    assert "required field" in form_js and ".form-remaining" in form_js
    assert "aria-invalid" in form_js and "innerHTML" not in form_js
