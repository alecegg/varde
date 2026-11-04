"""Comment widget design: markup, counter, sending states and stylesheet rules.

The widget matrix (`widget_matrix -k comment`) covers layout, contrast and focus
in Chromium.
"""

from __future__ import annotations

from pathlib import Path

from varde_learn.docs.pages.blocks_render.registry import COMPONENTS

PAGES = Path(__file__).resolve().parents[2] / "src/varde_learn/docs/pages"
CSS = (PAGES / "static/css/22-comment.css").read_text()
JS = (PAGES / "static/recap.js").read_text()


def _render() -> str:
    return COMPONENTS["comment"].render({"label": "Why?"}, "w")


def test_label_is_linked_to_textarea_and_counter_describes_it() -> None:
    out = _render()
    assert '<label class="comment-note" for="comment-text-w">Why?</label>' in out
    assert 'id="comment-text-w"' in out
    assert 'aria-describedby="comment-count-w"' in out
    assert 'id="comment-count-w"' in out
    assert 'class="comment-announce" aria-live="polite"' in out
    assert "style=" not in out and "<script" not in out


def test_send_row_keeps_state_and_alert_regions() -> None:
    out = _render()
    assert '<button type="submit" class="comment-send">Send</button>' in out
    assert 'class="comment-state" aria-live="polite"' in out
    assert 'id="comment-error-w" role="alert"' in out


def test_stylesheet_is_stacked_full_width_and_readable() -> None:
    assert "inline-size: 100%" in CSS and "flex-direction: column" in CSS
    assert "max(1rem, 16px)" in CSS and "field-sizing: content" in CSS
    assert "overflow-wrap: anywhere" in CSS and "forced-colors" in CSS
    assert ":disabled" in CSS and "focus-visible" in CSS
    assert "button:focus-visible" not in CSS


def test_script_announces_only_at_thresholds_and_shows_sending() -> None:
    assert "level === state.level" in JS
    assert "'Sending...'" in JS
    comment_js = JS.split("register('comment'")[1][:900]
    assert "textContent" in JS and "innerHTML" not in comment_js
