"""Page chrome stylesheet parts: token use only, logical properties, states."""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

import pytest

CSS_DIR = Path(str(files("varde_learn.docs.pages").joinpath("static", "css")))
OWNED = ("10-chrome.css", "50-blocks.css")
DECLARATION = re.compile(r"([a-z-]+)\s*:\s*([^;{}]+);")
LENGTH = re.compile(r"-?\d*\.?\d+(?:px|rem|em|vw|vh|ch)\b")
SPACING = re.compile(r"^(margin|padding|gap|row-gap|column-gap)(-|$)")
PHYSICAL = re.compile(
    r"\b(?:margin|padding|border)-(?:left|right|top|bottom)\b"
    r"|(?<![\w-])(?:left|right|top|bottom|width|height|min-width|min-height|max-width|max-height)\s*:"
    r"|text-align\s*:\s*(?:left|right)"
)


def _text(name: str) -> str:
    return re.sub(r"/\*.*?\*/", "", (CSS_DIR / name).read_text(), flags=re.DOTALL)


def _declarations(name: str) -> list[tuple[str, str]]:
    return [(p, v.strip()) for p, v in DECLARATION.findall(_text(name))]


@pytest.mark.parametrize("name", OWNED)
def test_font_sizes_come_from_tokens(name: str) -> None:
    bad = [
        v
        for p, v in _declarations(name)
        if p == "font-size" and not re.fullmatch(r"var\(--vd-[\w-]+\)|inherit", v)
    ]
    assert bad == []


@pytest.mark.parametrize("name", OWNED)
def test_spacing_comes_from_tokens(name: str) -> None:
    bad = []
    for prop, value in _declarations(name):
        if not SPACING.match(prop):
            continue
        stripped = re.sub(r"var\(--vd-[\w-]+\)|\d+vw", "", value)  # fluid vw step
        if LENGTH.search(stripped):
            bad.append(f"{prop}: {value}")
    assert bad == []


@pytest.mark.parametrize("name", OWNED)
def test_control_sizes_come_from_tokens(name: str) -> None:
    bad = [
        f"{p}: {v}"
        for p, v in _declarations(name)
        if p in ("min-block-size", "min-inline-size") and "px" in v
    ]
    assert bad == []


@pytest.mark.parametrize("name", OWNED)
def test_logical_properties_only(name: str) -> None:
    assert PHYSICAL.findall(_text(name)) == []


@pytest.mark.parametrize("name", OWNED)
def test_focus_is_never_removed(name: str) -> None:
    assert not re.search(r"outline\s*:\s*(?:none|0)\b", _text(name))


def test_button_family_has_every_state() -> None:
    css = _text("10-chrome.css")
    for selector in (
        "button:active", "button:focus-visible", "button:disabled",
        "button.primary", "button.ghost", "button.danger", "button:hover",
    ):  # fmt: skip
        assert selector in css, selector
    hover_start = css.index("@media (hover: hover)")
    assert css.index("button:hover") > hover_start


def test_thread_bar_is_a_logical_border() -> None:
    thread = re.search(r"\.thread \{([^}]*)\}", _text("10-chrome.css"))
    assert thread and "border-inline-start" in thread.group(1)


def test_flash_and_forced_colors_are_covered() -> None:
    css = _text("10-chrome.css")
    assert "prefers-reduced-motion: reduce" in css
    assert "forced-colors: active" in css


def test_button_targets_use_the_control_height_token() -> None:
    button = re.search(r"\nbutton \{([^}]*)\}", _text("10-chrome.css"))
    assert button
    assert "min-block-size: var(--vd-control-height)" in button.group(1)
    assert "min-inline-size: var(--vd-control-height)" in button.group(1)
