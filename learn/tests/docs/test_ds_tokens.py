"""Agent-Native visual bar: tone contrast, hairline elevation, density, doc layout."""

from __future__ import annotations

import colorsys
import re
from importlib.resources import files
from pathlib import Path

import pytest

CSS_DIR = Path(str(files("varde_learn.docs.pages").joinpath("static", "css")))
TONES = ("info", "decision", "risk", "warning", "success")
SURFACES = {
    "light": ((255, 255, 255), (245, 245, 245), (255, 255, 255)),
    "dark": ((23, 23, 23), (15, 15, 15), (35, 35, 35)),
}
TRIPLE = re.compile(r"(\d+) (\d+)% (\d+)%")
HSL = re.compile(r"hsl\((\d+) (\d+)% (\d+)%\)")
# classes the part files styled before the restyle; each must keep a rule
CLASSES = """
accept-btn actions align-center align-right arrow back block changed chart
choice-body choice-detail choice-error choice-grid choice-group choice-label
choice-note choice-option choice-options choice-question choice-send choice-state
choice-text comment-announce comment-count comment-error comment-field
comment-note comment-send comment-state comment-text composer danger
decision-approve decision-buttons decision-comment decision-deny decision-diff
decision-error decision-evidence decision-glyph decision-item decision-label
decision-note decision-question decision-send decision-state decision-status
decision-text decision-text-line decision-verdict dep-graph destructive diagram
doc-header doc-name done dragging edge error flow form-body form-checkbox
form-error form-field form-grid form-hint form-label form-remaining form-row
form-send form-state form-title ghost graph-empty graph-note meta missing node
orphans over-after over-before primary ranking-buttons ranking-grip ranking-hint
ranking-line ranking-list ranking-live ranking-move ranking-row ranking-text recap
recap-drift recap-error recap-file recap-state reply resolved scroll slider-end
slider-ends slider-error slider-group slider-input slider-label slider-send
slider-state slider-ticks slider-track slider-value status suggestion
task text thread vb vb-area vb-auth vb-auth-none vb-axis vb-badge vb-bar vb-bar-fill
vb-bar-num vb-bar-svg vb-bar-track vb-card vb-center vb-chart vb-col vb-controls
vb-ctl vb-data vb-data-grid vb-data-scroll vb-dense vb-dot vb-end vb-error vb-filter
vb-filter-status vb-filterbar vb-flow vb-flowbar vb-foot vb-grid vb-group-head
vb-badge-key vb-hash vb-hit vb-key vb-key-mark vb-last vb-legend vb-line
vb-method vb-na vb-name
vb-next vb-note vb-note-label vb-nowrap vb-num vb-off vb-on vb-open vb-pct vb-plot
vb-r1 vb-r2 vb-r3 vb-r4 vb-r5 vb-readout vb-region vb-rel vb-relations vb-s0 vb-s1
vb-s2 vb-s3 vb-s4 vb-s5 vb-scroll vb-scrollhint vb-series-toggle vb-slice
vb-slice-key vb-sort vb-sortpick vb-sortselect vb-spark vb-state vb-status
vb-status-bad vb-status-neutral vb-status-ok vb-status-warn vb-step vb-sym vb-tab
vb-table vb-table-stack vb-table-sticky vb-tabs vb-tick vb-tip vb-tip-box
vb-tip-text vb-title vb-wire vb-wrap-toggle vd-cap vd-chev vd-dashed vd-detail
vd-dim vd-dotted vd-edge vd-elabel vd-elabel-bg vd-frame vd-g1 vd-g2 vd-g3
vd-group-head vd-group-label vd-head vd-head-hit vd-hot vd-label vd-line vd-near
vd-node vd-sel vd-shape vd-super vd-svg vd-view vf-down vf-up vw-bar vw-bezel vw-box
vw-compare vw-detail vw-dot vw-fig vw-frames vw-hatch vw-hot vw-kind vw-note
vw-note-on vw-notes vw-pin vw-region vw-region-label vw-screen vw-sel vw-svg vw-view
wireframe
""".split()  # noqa: SIM905


def _css(name: str) -> str:
    return re.sub(
        r"/\*.*?\*/", "", (CSS_DIR / f"{name}.css").read_text(), flags=re.DOTALL
    )


def _body(css: str, start: int) -> tuple[str, int]:
    open_at = css.index("{", start)
    depth, i = 0, open_at
    while True:
        depth += css[i] == "{"
        depth -= css[i] == "}"
        i += 1
        if depth == 0:
            return css[open_at + 1 : i - 1], i


def _decls(body: str) -> dict[str, str]:
    return {k: v.strip() for k, v in re.findall(r"(--vd-[\w-]+)\s*:\s*([^;]+);", body)}


def _scheme_tokens(scheme: str) -> dict[str, str]:
    css = _css("00-tokens")
    root, _ = _body(css, css.index(":root"))
    tokens = _decls(root)
    if scheme == "dark":
        media = css.index("@media (prefers-color-scheme: dark)")
        dark, _ = _body(css, media)
        inner, _ = _body(dark, dark.index(":root"))
        tokens |= _decls(inner)
    return tokens


def _rgb(h: float, s: float, light: float) -> tuple[float, ...]:
    r, g, b = colorsys.hls_to_rgb(h / 360, light / 100, s / 100)
    return (r * 255, g * 255, b * 255)


def _lum(rgb: tuple[float, ...]) -> float:
    def ch(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * ch(rgb[0]) + 0.7152 * ch(rgb[1]) + 0.0722 * ch(rgb[2])


def _ratio(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _mix(
    top: tuple[float, ...], alpha: float, below: tuple[float, ...]
) -> tuple[float, ...]:
    return tuple(top[i] * alpha + below[i] * (1 - alpha) for i in range(3))


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("tone", TONES)
def test_tone_edge_and_text_meet_contrast(scheme: str, tone: str) -> None:
    tokens = _scheme_tokens(scheme)
    h, s, light = map(int, TRIPLE.fullmatch(tokens[f"--vd-tone-{tone}"]).groups())  # type: ignore[union-attr]
    th, ts, tl = map(int, HSL.fullmatch(tokens[f"--vd-tone-{tone}-text"]).groups())  # type: ignore[union-attr]
    edge, text = _rgb(h, s, light), _rgb(th, ts, tl)
    page, sunk, elevated = SURFACES[scheme]
    assert _ratio(edge, page) >= 3.0, f"{scheme} {tone} edge on page"
    for ground in (page, sunk, elevated):
        tinted = _mix(edge, 0.08, ground)
        assert _ratio(text, tinted) >= 4.5, (
            f"{scheme} {tone} text on tint over {ground}"
        )


def test_dark_triples_are_ten_lightness_points_above_light() -> None:
    light, dark = _scheme_tokens("light"), _scheme_tokens("dark")
    for tone in TONES:
        lh, ls, ll = map(int, TRIPLE.fullmatch(light[f"--vd-tone-{tone}"]).groups())  # type: ignore[union-attr]
        dh, ds, dl = map(int, TRIPLE.fullmatch(dark[f"--vd-tone-{tone}"]).groups())  # type: ignore[union-attr]
        assert (dh, ds, dl) == (lh, ls, ll + 10)


def test_tones_follow_the_bar_triples() -> None:
    light = _scheme_tokens("light")
    assert [light[f"--vd-tone-{t}"] for t in TONES] == [
        "218 85% 57%", "262 83% 58%", "0 84% 60%", "25 95% 48%", "142 71% 38%",
    ]  # fmt: skip


def test_forced_colors_maps_every_tone_to_system_colours() -> None:
    css = _css("00-tokens")
    body, _ = _body(css, css.index("@media (forced-colors: active)"))
    forced = _decls(body)
    for tone in TONES:
        assert forced[f"--vd-tone-{tone}-edge"] == "CanvasText"
        assert forced[f"--vd-tone-{tone}-text"] == "CanvasText"


def test_neutral_ramp_is_ten_forty_five_ninety_ninety_five() -> None:
    light = _scheme_tokens("light")
    assert light["--vd-neutral-text"] == "hsl(0 0% 10%)"
    assert light["--vd-neutral-muted"] == "hsl(0 0% 45%)"
    assert light["--vd-line"] == "hsl(0 0% 90%)"
    assert light["--vd-fill"] == "hsl(0 0% 95%)"


def test_no_blurred_box_shadow_anywhere() -> None:
    for scheme in ("light", "dark"):
        for name, value in _scheme_tokens(scheme).items():
            if name.startswith("--vd-shadow"):
                assert value == "none", name
    for part in sorted(CSS_DIR.glob("*.css")):
        for value in re.findall(r"box-shadow\s*:\s*([^;}]+)", _css(part.stem)):
            spread_only = re.fullmatch(
                r"0 -?\d+px 0 0 [^,]+|0 0 0 \d+px [^,]+|none|var\(--vd-shadow-\d\)",
                value.strip(),
            )
            assert spread_only, f"{part.name}: {value}"


def test_every_pre_existing_class_still_has_a_rule() -> None:
    css = "\n".join(_css(p.stem) for p in sorted(CSS_DIR.glob("*.css")))
    selectors = re.sub(r"\{[^{}]*\}", ";", css)
    missing = [
        c for c in CLASSES if not re.search(rf"\.{re.escape(c)}(?![\w-])", selectors)
    ]
    assert missing == []


@pytest.mark.parametrize("preset", ["compact", "roomy"])
def test_density_attribute_switches_the_vars(preset: str) -> None:
    css = _css("00-tokens")
    default = _decls(_body(css, css.index(":root"))[0])
    body, _ = _body(css, css.index(f'[data-density="{preset}"]'))
    switched = _decls(body)
    names = {n for n in default if n.startswith("--vd-density-")}
    assert names == {
        f"--vd-density-{k}" for k in ("gap", "pad", "font", "radius", "stroke")
    }
    assert set(switched) == names
    assert switched != {n: default[n] for n in names}


def test_page_is_a_container_with_a_60rem_column_and_1_75_body() -> None:
    base, tokens = _css("01-base"), _css("00-tokens")
    assert "container: vd-doc / inline-size" in base
    assert "--vd-doc-width: 60rem" in tokens and "--vd-toc-width: 11rem" in tokens
    assert "--vd-body-leading: 1.75" in tokens
    assert "var(--vd-body-leading)" in base


def test_toc_is_a_collapsed_block_by_default_and_a_rail_from_64rem() -> None:
    base = _css("01-base")
    assert not re.search(r"\.doc-toc\s*\{[^}]*display:\s*none", base)
    start = base.index("@container vd-doc (min-width: 64rem)")
    inside, _ = _body(base, start)
    assert "display: block" in inside and "position: sticky" in inside
    assert "var(--vd-toc-width)" in inside
