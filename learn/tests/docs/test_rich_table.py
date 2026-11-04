"""Rich table: validation, server HTML, copy text, stylesheet, keyboard behaviour."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks import check_props
from varde_learn.docs.pages.blocks.tables import numeric
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.blocks_render.tables import (
    bar_percent,
    copy_text,
    status_kind,
)
from varde_learn.docs.pages.serve import PageServer

PAGES = Path(str(files("varde_learn.docs.pages")))
CSS = re.sub(
    r"/\*.*?\*/",
    "",
    (PAGES / "static" / "css" / "40-table.css").read_text(),
    flags=re.DOTALL,
)
JS = (PAGES / "static" / "table.js").read_text()
PHYSICAL = re.compile(
    r"\b(?:margin|padding|border)-(?:left|right|top|bottom)\b"
    r"|(?<![\w-])(?:left|right|top|bottom|width|height|min-width|min-height)\s*:"
)
COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla)\(")

RICH = {
    "caption": "Services",
    "columns": ["service", "owner", "latency", "load", "state", "docs"],
    "types": {
        "latency": "number",
        "load": "bar",
        "state": "status",
        "docs": "link",
    },
    "rows": [
        ["api", "core", 120, 80, "ok", "https://example.com/api"],
        ["db", "data", "45.5", 20, "degraded", ["Runbook", "/runbooks/db"]],
        ["queue", "core", 9, 50, "failed", "javascript:alert(1)"],
        ["cache", "data", 3, 5, "ok", ["Cache <docs>", "https://example.com/c"]],
    ],
    "footnote": "Latency in ms.",
    "sticky_column": True,
    "stack": True,
    "groups": [{"label": "Core", "rows": 2}, {"label": "Data", "rows": 2}],
}


def _render(**over: Any) -> str:
    data = {**RICH, **over}
    return COMPONENTS["table"].render(data, "t")


def _faults(**over: Any) -> list[str]:
    data = {**RICH, **over}
    return [f.rule for f in check_props("table", data, 1)]


def test_existing_props_stay_valid_and_new_props_are_optional() -> None:
    plain = {"columns": ["a"], "rows": [["1"]], "caption": "c"}
    assert check_props("table", plain, 1) == []
    assert _faults() == []


@pytest.mark.parametrize(
    ("over", "rule"),
    [
        ({"types": {"nope": "number"}}, "types-column"),
        ({"types": {"owner": "colour"}}, "types-kind"),
        ({"types": {"owner": 1}}, "type"),
        ({"types": {"owner": "number"}}, "cell-number"),
        ({"types": {"owner": "link", "latency": "number"}}, None),
        ({"sticky_column": "yes"}, "type"),
        ({"stack": 1}, "type"),
        ({"footnote": ""}, "type"),
        ({"groups": [{"label": "A", "rows": 3}]}, "group-rows"),
        ({"groups": [{"label": "A"}]}, "missing-key"),
        ({"groups": [{"label": "A", "rows": 0}]}, "type"),
        ({"groups": "x"}, "type"),
    ],
)
def test_validation_faults(over: dict[str, Any], rule: str | None) -> None:
    faults = _faults(**over)
    if rule is None:
        assert faults == []
    else:
        assert rule in faults


def test_link_cell_must_be_a_url_or_a_pair() -> None:
    data = {**RICH, "rows": [["a", "b", 1, 1, "ok", 5]]}
    del data["groups"]
    assert "cell-link" in [f.rule for f in check_props("table", data, 1)]


def test_numeric_helper() -> None:
    assert numeric(3) and numeric("4.5") and numeric("-2")
    assert not numeric("x") and not numeric(True) and not numeric(["1"])


def test_markup_roles_scope_and_labels() -> None:
    out = _render()
    assert out.startswith('<div class="vb table" data-copy="')
    assert 'role="region" tabindex="0" aria-label="Services"' in out
    assert 'aria-label="Services (4 rows, 6 columns)"' in out
    assert out.count('<th scope="col"') == 6
    assert 'class="vb-table vb-table-stack vb-table-sticky"' in out
    assert '<th scope="row" data-label="service">api</th>' in out
    assert out.count("<tbody>") == 2 and out.count('class="vb-group-head"') == 2
    assert 'data-label="latency"' in out and 'class="vb-num"' in out
    assert 'class="vb-alt vb-foot">Latency in ms.</p>' in out


def test_footnote_defaults_to_a_size_summary() -> None:
    out = COMPONENTS["table"].render({"columns": ["a"], "rows": [["1"], ["2"]]}, None)
    assert "2 rows, 1 columns" in out and "<h4" not in out


def test_typed_cells() -> None:
    out = _render()
    assert 'class="vb-status vb-status-ok"' in out and "✓" in out
    assert "vb-status-warn" in out and "vb-status-bad" in out
    assert out.count('class="vb-bar-svg"') == 4 and 'aria-hidden="true"' in out
    assert '<rect class="vb-bar-fill" width="100.0"' in out  # largest value is full
    assert '<span class="vb-bar-num">80</span>' in out


def test_links_go_through_classify_url_and_escape() -> None:
    out = _render()
    assert 'href="https://example.com/api" rel="noopener noreferrer"' in out
    assert '<span class="relative-link" title="/runbooks/db">Runbook</span>' in out
    assert 'href="javascript' not in out and '<a href="j' not in out
    assert "<docs>" not in out and "Cache &lt;docs&gt;" in out


def test_all_text_from_props_is_escaped_and_nothing_is_inline() -> None:
    out = _render(
        caption="<c>",
        footnote="<f>",
        columns=["<h>"] + RICH["columns"][1:],
        rows=[["<d>", "o", 1, 1, "<s>", "u"]],
        groups=None,
    )
    for raw in ("<c>", "<f>", "<h>", "<d>", "<s>"):
        assert raw not in out
    assert (
        "style=" not in out
        and "<script" not in out
        and " on" not in re.sub(r'"[^"]*"', "", out)
    )


def test_copy_text_is_tab_separated_with_group_column() -> None:
    out = _render()
    match = re.search(r'data-copy="([^"]*)"', out)
    assert match
    lines = match.group(1).replace("&quot;", '"').split("\n")
    assert lines[0] == "group\tservice\towner\tlatency\tload\tstate\tdocs"
    assert lines[1].startswith("Core\tapi\tcore\t120\t80\tok\thttps://example.com/api")
    assert "db\tdata\t45.5\t20\tdegraded\tRunbook (/runbooks/db)" in lines[2]
    assert len(lines) == 5


def test_copy_text_flattens_tabs_and_breaks() -> None:
    assert copy_text(["a\tb"], [["x\ny"]], []) == "a b\nx y"


def test_status_and_bar_helpers() -> None:
    assert status_kind("OK") == ("ok", "✓")
    assert status_kind("blocked")[0] == "bad" and status_kind("zzz")[0] == "neutral"
    assert bar_percent(5, 20) == 25 and bar_percent(-3, 20) == 0
    assert bar_percent(1, 0) == 0 and bar_percent(30, 20) == 100


def test_stylesheet_is_tokens_logical_and_covers_modes() -> None:
    assert COLOUR_LITERAL.findall(CSS) == []
    assert PHYSICAL.findall(CSS) == []
    for needle in (
        "position: sticky",
        "inset-block-start: 0",
        "inset-inline-start: 0",
        "tabular-nums",
        "var(--vd-surface-sunk)",
        "var(--vd-hover)",
        "attr(data-label)",
        "forced-colors: active",
        "@media print",
        "max-inline-size: 100%",
    ):
        assert needle in CSS, needle


def test_script_uses_no_html_injection_or_inline_style() -> None:
    for banned in ("innerHTML", "insertAdjacentHTML", "setAttribute('style'", "eval("):
        assert banned not in JS


# ---- Chromium (slow tier) ---------------------------------------------------

BODY_ROWS = "".join(
    f'["svc{n:02d}", {n * 7 % 50}, "{"ok" if n % 3 else "failed"}"], '
    for n in range(30)
)
DOC = f"""# Rich table

```ui id=rich
rich = table(
  caption: "Services",
  columns: ["service", "latency", "state"],
  types: {{"latency": "number", "state": "status"}},
  rows: [{BODY_ROWS}],
  sticky_column: true,
  stack: true,
)
```
"""


@pytest.fixture
def site(tmp_path: Path) -> Iterator[PageServer]:
    doc = tmp_path / "plan.md"
    doc.write_text(DOC)
    server = PageServer(doc, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(5)


@pytest.fixture(scope="module")
def shared_page(browser_session: Any) -> Any:
    page = browser_session.new_page(viewport={"width": 1024, "height": 700})
    page.set_default_timeout(10_000)
    return page


def _open(page: Any, server: PageServer, width: int = 1024) -> None:
    page.set_viewport_size({"width": width, "height": 700})
    page.route("**/events", lambda route: route.abort())
    page.goto(f"http://127.0.0.1:{server.port}/")
    page.wait_for_selector(".vb-filterbar")


def _first_column(page: Any) -> list[str]:
    return page.locator("tbody tr:visible th:first-child").all_text_contents()


@pytest.mark.slow
def test_interact_sort_and_filter_by_keyboard(
    shared_page: Any, site: PageServer
) -> None:
    page = shared_page
    _open(page, site)
    sort = page.locator("thead th").nth(1).locator(".vb-sort")
    sort.focus()
    page.keyboard.press("Enter")
    assert page.locator("thead th").nth(1).get_attribute("aria-sort") == "ascending"
    assert _first_column(page)[0] == "svc00"
    page.keyboard.press("Enter")
    assert page.locator("thead th").nth(1).get_attribute("aria-sort") == "descending"
    page.keyboard.press("Enter")
    assert page.locator("thead th").nth(1).get_attribute("aria-sort") == "none"
    page.locator(".vb-filter").fill("svc1")
    assert page.locator(".vb-filter-status").inner_text() == "10 of 30 rows"
    assert len(_first_column(page)) == 10


@pytest.mark.slow
def test_interact_region_is_focusable_and_header_stays_visible(
    shared_page: Any, site: PageServer
) -> None:
    page = shared_page
    _open(page, site)
    region = page.locator(".vb-scroll")
    assert region.get_attribute("tabindex") == "0"
    region.focus()
    assert region.evaluate("e => document.activeElement === e")
    region.evaluate("e => { e.scrollTop = 200; }")
    assert region.evaluate("e => e.scrollTop") > 0
    top = region.evaluate("e => e.getBoundingClientRect().top")
    head = page.locator("thead th").first.evaluate("e => e.getBoundingClientRect().top")
    assert abs(head - top) <= 2


@pytest.mark.slow
def test_interact_wrap_toggle_by_keyboard(shared_page: Any, site: PageServer) -> None:
    page = shared_page
    _open(page, site)
    button = page.locator(".vb-wrap-toggle")
    assert button.get_attribute("aria-pressed") == "true"
    button.focus()
    page.keyboard.press("Enter")
    assert button.get_attribute("aria-pressed") == "false"
    assert "vb-nowrap" in page.locator(".vb-scroll").get_attribute("class")
    page.keyboard.press("Space")
    assert "vb-nowrap" not in page.locator(".vb-scroll").get_attribute("class")


@pytest.mark.slow
def test_interact_stack_mode_on_phone_widths(
    shared_page: Any, site: PageServer
) -> None:
    page = shared_page
    _open(page, site, width=390)
    cell = page.locator("tbody tr").first.locator("td").first
    assert cell.evaluate("e => getComputedStyle(e).display") == "grid"
    label = cell.evaluate("e => getComputedStyle(e, '::before').content")
    assert label == '"latency"'
    assert page.locator("thead").evaluate("e => e.getBoundingClientRect().width") <= 1
    _open(page, site, width=1024)
    assert (
        page.locator("tbody tr")
        .first.locator("td")
        .first.evaluate("e => getComputedStyle(e).display")
        == "table-cell"
    )


@pytest.mark.slow
def test_interact_phone_sorts_through_the_select_not_hidden_buttons(
    shared_page: Any, site: PageServer
) -> None:
    page = shared_page
    _open(page, site, width=390)
    pick = page.locator(".vb-sortselect")
    assert pick.is_visible()
    assert (
        page.locator("thead .vb-sort").first.evaluate(
            "e => getComputedStyle(e).visibility"
        )
        == "hidden"
    )
    pick.focus()
    pick.select_option("1:-1")
    assert page.locator("thead th").nth(1).get_attribute("aria-sort") == "descending"
    assert page.locator("tbody tr").first.locator("th").inner_text() == "svc07"
    pick.select_option("")
    assert page.locator("thead th").nth(1).get_attribute("aria-sort") == "none"
    _open(page, site, width=1024)
    assert not page.locator(".vb-sortselect").is_visible()


WIDE = """# Wide

```ui id=wide
wide = table(
  columns: ["service", "owner", "latency ms", "load", "state", "docs"],
  types: {"latency ms": "number", "load": "number"},
  rows: [["a-long-service-name", "team owning it", 1, 2, "ok", "https://example.com"]],
  sticky_column: true,
)
```
"""


@pytest.mark.slow
def test_interact_focus_keeps_the_last_sort_button_inside_the_region(
    shared_page: Any, tmp_path: Path
) -> None:
    doc = tmp_path / "wide.md"
    doc.write_text(WIDE)
    server = PageServer(doc, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        page = shared_page
        _open(page, server, width=320)
        page.locator("thead .vb-sort").last.focus()
        margins = page.evaluate(
            """() => {
              const box = document.querySelector('.vb-scroll').getBoundingClientRect();
              const r = document.activeElement.getBoundingClientRect();
              return [r.left - box.left, box.right - r.right];
            }"""
        )
        assert min(margins) >= 4
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def _rule(selector: str) -> str:
    return next(
        b
        for sel, b in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS)
        if sel.strip().startswith(selector)
    )


def test_cells_wrap_only_at_word_boundaries_and_tokens_stay_whole() -> None:
    cell = _rule(".vb-table th, .vb-table td")
    assert "overflow-wrap: normal" in cell and "word-break: normal" in cell
    assert "hyphens: none" in cell
    assert "white-space: nowrap" in _rule(".vb-table .vb-status")
    assert "min-inline-size: min-content" in _rule(".vb-table")


def test_print_block_is_last_and_resets_the_screen_rules() -> None:
    print_block = CSS[CSS.rindex("@media print") :]
    assert print_block == CSS[CSS.index("@media print") :]
    for needle in (
        "white-space: normal",
        "overflow-wrap: anywhere",
        "min-inline-size: 0",
        "table-layout: fixed",
        "overflow: visible",
    ):
        assert needle in print_block


def test_iso_dates_in_cells_cannot_break_at_hyphens() -> None:
    from varde_learn.docs.pages.blocks_render.tables import cell_html, copy_text

    assert cell_html("2026-11-01", "text", 0) == (
        '<span class="vd-date">2026-11-01</span>'
    )
    assert cell_html("due 2026-11-01 <b>", "text", 0) == (
        'due <span class="vd-date">2026-11-01</span> &lt;b&gt;'
    )
    assert copy_text(["d"], [["2026-11-01"]], []) == "d\n2026-11-01"


def test_print_lets_table_dates_wrap_in_fixed_columns() -> None:
    css = (PAGES / "static" / "css" / "40-table.css").read_text()
    assert ".vb-table .vd-date" in css[css.index("@media print") :]
