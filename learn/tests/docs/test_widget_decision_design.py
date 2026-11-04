"""Decision widget design: markup, glyph cues and stylesheet rules.

The widget matrix (`widget_matrix -k decision`) covers layout, contrast and focus
in Chromium.
"""

from __future__ import annotations

from pathlib import Path

from varde_learn.docs.pages.blocks_render.registry import COMPONENTS

PAGES = Path(__file__).resolve().parents[2] / "src/varde_learn/docs/pages"
CSS = (PAGES / "static/css/23-decision.css").read_text()
PROPS = {
    "question": "Ship?",
    "evidence": [{"label": "tests", "text": "green"}],
    "diff": "+a\n-b",
}


def _render() -> str:
    return COMPONENTS["decision"].render(PROPS, "w")


def test_verdict_buttons_carry_a_glyph_and_a_text_label() -> None:
    out = _render()
    assert (
        'data-verdict="approved"><span class="decision-glyph" aria-hidden="true">'
        in out
    )
    assert "<span>Approve</span>" in out and "<span>Deny</span>" in out
    assert 'role="group" aria-label="Verdict"' in out
    assert "style=" not in out and "<script" not in out


def test_comment_label_is_linked_and_state_starts_undecided() -> None:
    out = _render()
    assert 'for="decision-text-w"' in out and 'id="decision-text-w"' in out
    assert 'class="decision-state" aria-live="polite">Undecided<' in out
    assert 'class="decision-error" role="alert"' in out


def test_diff_scrolls_and_is_keyboard_reachable() -> None:
    assert '<pre class="decision-diff" tabindex="0">' in _render()
    assert "overflow: auto" in CSS and "focus-visible" in CSS


def test_stylesheet_wraps_and_keeps_the_global_button_ring() -> None:
    assert "flex-wrap: wrap" in CSS and "overflow-wrap: anywhere" in CSS
    assert "forced-colors" in CSS and "max(1rem, 16px)" in CSS
    assert "button:focus-visible" not in CSS
