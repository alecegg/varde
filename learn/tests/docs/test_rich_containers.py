"""tabs and columns: held blocks rendered once, faults, menus, export, interactions."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.assemble import assemble_page, assemble_static
from varde_learn.docs.pages.blocks import check, check_props
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.serve import PageServer

FIXTURES = Path(__file__).parent / "fixtures" / "widgets"
TOKEN = "t"  # noqa: S105
MAIN = re.compile(r'<main data-role="page">(.*)</main>', re.DOTALL)


def write(tmp_path: Path, text: str) -> Path:
    doc = tmp_path / "plan.md"
    doc.write_text(text, encoding="utf-8")
    return doc


def statements(*lines: str) -> str:
    return "".join(f"```ui\n{line}\n```\n\n" for line in lines)


CALL = 'a = callout(tone: "info", text: "A")'
CALL_B = 'b = callout(tone: "info", text: "B")'
INPUT = 'q = choice(question: "Pick", options: [{"label": "x"}, {"label": "y"}])'


def tabs(*panels: str, ident: str = "t") -> str:
    return f"{ident} = tabs(tab: [{', '.join(panels)}])"


def panel(label: str, *ids: str) -> str:
    held = ", ".join(f'"{i}"' for i in ids)
    return f'{{"label": "{label}", "blocks": [{held}]}}'


def rules(text: str) -> list[str]:
    return [e.rule for e in check(text)]


def test_registered_components_and_shape_faults() -> None:
    assert {"tabs", "columns"} <= COMPONENTS.keys()
    ok: dict[str, object] = {"tab": [{"label": "A", "blocks": ["a"]}]}
    assert check_props("tabs", ok, 1) == []
    assert check_props("columns", {"col": [{"blocks": ["a"]}]}, 1) == []
    bad: list[tuple[str, dict[str, object]]] = [
        ("tabs", {}),
        ("tabs", {"tab": []}),
        ("tabs", {"tab": [{"blocks": ["a"]}]}),
        ("tabs", {"tab": [{"label": "A", "blocks": []}]}),
        ("tabs", {"tab": [{"label": "A", "blocks": ["Bad Id"]}]}),
        ("tabs", {"tab": [{"label": "A", "blocks": ["a"], "x": 1}]}),
        ("columns", {"col": [{"blocks": ["a"]}] * 5}),
    ]
    for name, data in bad:
        assert check_props(name, data, 1), (name, data)


def test_document_faults_name_each_case() -> None:
    page = statements(CALL, CALL_B, INPUT)
    assert rules(page + statements(tabs(panel("A", "a")))) == []
    assert "container-unknown" in rules(page + statements(tabs(panel("A", "zzz"))))
    assert "container-input" in rules(page + statements(tabs(panel("A", "q"))))
    cols = 'c = columns(col: [{"blocks": ["q"]}])'
    assert rules(page + statements(cols)) == []
    assert "container-double" in rules(
        page + statements(tabs(panel("A", "a"), panel("B", "a")))
    )
    two = statements(tabs(panel("A", "a")), tabs(panel("B", "a"), ident="u"))
    assert "container-double" in rules(page + two)
    nested = statements(tabs(panel("A", "u")), tabs(panel("B", "a"), ident="u"))
    assert "container-nested" in rules(page + nested)
    assert "container-cycle" in rules(page + statements(tabs(panel("A", "t"))))
    loop = statements(tabs(panel("A", "u")), tabs(panel("B", "t"), ident="u"))
    assert "container-cycle" in rules(page + loop)


def test_held_blocks_may_come_before_or_after_the_container() -> None:
    page = (
        statements(CALL) + statements(tabs(panel("A", "a", "b"))) + statements(CALL_B)
    )
    assert rules(page) == []


def render(tmp_path: Path, text: str) -> str:
    return assemble_page(write(tmp_path, text), token=TOKEN)


def block_ids(html: str) -> list[str]:
    return re.findall(r'<div class="block" id="blk-([a-z0-9-]+)"', html)


def test_held_block_is_rendered_once_inside_its_panel(tmp_path: Path) -> None:
    text = (FIXTURES / "rich-containers.md").read_text(encoding="utf-8")
    html = render(tmp_path, text)
    ids = block_ids(html)
    assert len(ids) == len(set(ids))
    for held in ("code1", "diff1", "tree1", "list1", "note1", "c2"):
        assert html.count(f'id="blk-{held}"') == 1
    tab = html[html.index('class="vb tabs') : html.index('class="vb columns')]
    for held in ("code1", "diff1", "tree1", "list1"):
        assert f'id="blk-{held}"' in tab
    assert html.index('id="blk-tabs1"') < html.index('id="blk-code1"')
    assert html.index('id="blk-code1"') < html.index('id="blk-diff1"')
    assert html.index('id="blk-diff1"') < html.index('id="blk-list1"')


def test_labels_headings_and_order(tmp_path: Path) -> None:
    html = render(tmp_path, (FIXTURES / "rich-containers.md").read_text("utf-8"))
    labels = re.findall(r'class="vd-containers-label" id="[^"]*">([^<]*)</h4>', html)
    assert labels == ["Code", "Change", "Checks", "Context", "Code"]
    assert 'aria-labelledby="vd-ctab-tabs1-1-h"' in html


def test_held_blocks_keep_their_types_and_so_their_own_menus(tmp_path: Path) -> None:
    html = render(tmp_path, (FIXTURES / "rich-containers.md").read_text("utf-8"))
    kinds = dict(
        re.findall(
            r'id="blk-([a-z0-9-]+)" data-anchor="[^"]*" data-hash="[^"]*" '
            r'data-block-type="(\w+)"',
            html,
        )
    )
    assert kinds["code1"] == "code"
    assert kinds["diff1"] == "code"
    assert kinds["tree1"] == "visual"
    assert kinds["tabs1"] == "visual"


def test_container_copy_joins_labels_and_held_copy(tmp_path: Path) -> None:
    html = render(tmp_path, (FIXTURES / "rich-containers.md").read_text("utf-8"))
    root = re.search(r'<section class="vb tabs[^>]*data-copy="([^"]*)"', html)
    assert root is not None
    copy = root.group(1)
    assert copy.index("Code") < copy.index("Change") < copy.index("Checks")
    assert "queue.append(item)" in copy
    assert "Queue keeps order" in copy


def test_hash_changes_when_a_held_block_changes(tmp_path: Path) -> None:
    def hash_of(callout_text: str) -> str:
        page = statements(f'a = callout(tone: "info", text: "{callout_text}")')
        page += statements(tabs(panel("A", "a")))
        html = render(tmp_path, page)
        return re.search(r'id="blk-t" data-anchor="t" data-hash="(\w+)"', html).group(1)  # type: ignore[union-attr]

    assert hash_of("one") != hash_of("two")


def test_faults_render_a_note_not_a_crash(tmp_path: Path) -> None:
    page = statements(CALL, INPUT, tabs(panel("A", "zzz", "q", "a")))
    html = render(tmp_path, page)
    assert "is missing" in html
    assert "cannot be held in tabs" in html
    assert 'id="blk-q"' in html and 'id="blk-a"' in html
    again = statements(CALL, tabs(panel("A", "a")), tabs(panel("B", "a"), ident="u"))
    assert "held elsewhere" in render(tmp_path, again)
    self_hold = statements(tabs(panel("A", "t")))
    assert "is this container" in render(tmp_path, self_hold)
    inner = statements(tabs(panel("A", "u")), tabs(panel("B", "t"), ident="u"))
    assert "do not nest" in render(tmp_path, inner)


def test_hostile_strings_are_escaped(tmp_path: Path) -> None:
    page = statements(CALL, tabs(panel("<script>alert(1)</script>", "a")))
    html = render(tmp_path, page)
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_no_script_and_no_inline_style_in_the_markup(tmp_path: Path) -> None:
    html = render(tmp_path, (FIXTURES / "rich-containers.md").read_text("utf-8"))
    assert "style=" not in re.sub(r"<style.*?</style>", "", html, flags=re.DOTALL)


def test_all_panels_are_in_the_server_markup_and_none_hidden(tmp_path: Path) -> None:
    html = render(tmp_path, (FIXTURES / "rich-containers.md").read_text("utf-8"))
    assert html.count('class="vd-containers-panel vd-ctabs-panel"') == 3
    assert " hidden" not in html[html.index("vb tabs") : html.index("vb columns")]


def test_export_equals_the_live_page_minus_script(tmp_path: Path) -> None:
    doc = write(tmp_path, (FIXTURES / "rich-containers.md").read_text("utf-8"))
    live = MAIN.search(assemble_page(doc, token=TOKEN))
    static = assemble_static(doc)
    exported = MAIN.search(static)
    assert live is not None and exported is not None
    assert "<script" not in static
    assert exported.group(1) == live.group(1)


def test_stress_fixture_checks_and_renders(tmp_path: Path) -> None:
    text = (FIXTURES / "rich-containers-stress.md").read_text("utf-8")
    assert check(text) == []
    html = render(tmp_path, text)
    ids = block_ids(html)
    assert len(ids) == len(set(ids))
    assert "<script>alert" not in html
    assert html.count('class="vd-containers-slot"') >= 200


@pytest.mark.parametrize("name", ["rich-containers", "rich-containers-stress"])
def test_fixture_family_exists(name: str) -> None:
    assert (FIXTURES / f"{name}.md").exists()


# --- interactions (browser; the lead runs the slow tier) ---


@pytest.fixture(scope="module")
def shared_page(browser_session: Any) -> Any:
    page = browser_session.new_page(viewport={"width": 900, "height": 700})
    page.set_default_timeout(10_000)
    return page


@pytest.fixture
def open_page(tmp_path: Path, shared_page: Any) -> Iterator[Any]:
    doc = write(tmp_path, (FIXTURES / "rich-containers.md").read_text("utf-8"))
    server = PageServer(doc, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    problems: list[str] = []
    shared_page.on("pageerror", lambda error: problems.append(str(error)))
    shared_page.goto(f"http://127.0.0.1:{server.port}/")
    shared_page.wait_for_selector(".vd-ctabs-tab")
    yield shared_page
    assert problems == []
    shared_page.goto("about:blank")
    server.shutdown()
    server.server_close()
    thread.join(5)


def selected(page: Any) -> str:
    return page.locator('.vd-ctabs-tab[aria-selected="true"]').inner_text()


@pytest.mark.slow
def test_interact_arrows_home_end_and_enter_move_across_tabs(open_page: Any) -> None:
    page = open_page
    tabs_ = page.locator(".vd-ctabs-tab")
    assert tabs_.count() == 3
    tabs_.first.focus()
    page.keyboard.press("ArrowRight")
    assert selected(page) == "Change"
    page.keyboard.press("End")
    assert selected(page) == "Checks"
    page.keyboard.press("ArrowRight")
    assert selected(page) == "Code"
    page.keyboard.press("ArrowLeft")
    assert selected(page) == "Checks"
    page.keyboard.press("Home")
    assert selected(page) == "Code"
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Enter")
    assert selected(page) == "Change"


@pytest.mark.slow
def test_interact_tabs_are_44px_and_focus_stays_after_selection(open_page: Any) -> None:
    page = open_page
    for index in range(3):
        assert page.locator(".vd-ctabs-tab").nth(index).bounding_box()["height"] >= 44
    tab = page.locator(".vd-ctabs-tab").nth(1)
    tab.click()
    assert tab.evaluate("(el) => el === document.activeElement")
    assert tab.get_attribute("aria-selected") == "true"


@pytest.mark.slow
def test_interact_panel_is_labelled_by_its_tab_and_others_hidden(
    open_page: Any,
) -> None:
    page = open_page
    tab = page.locator(".vd-ctabs-tab").nth(1)
    tab.click()
    panel_ = page.locator('.vd-ctabs-panel[role="tabpanel"]').nth(1)
    assert panel_.get_attribute("aria-labelledby") == tab.get_attribute("id")
    assert panel_.is_visible()
    assert not page.locator(".vd-ctabs-panel").nth(0).is_visible()
    region = page.locator(".vd-ctabs-scroll")
    assert region.get_attribute("role") == "region"
    assert region.get_attribute("tabindex") == "0"


@pytest.mark.slow
def test_interact_held_blocks_keep_one_menu_each(open_page: Any) -> None:
    page = open_page
    page.wait_for_selector("#blk-code1 > .menu-btn", state="attached")
    assert page.locator("#blk-code1 > .menu-btn").count() == 1
    assert page.locator("#blk-tabs1 > .menu-btn").count() == 1
    assert page.locator("#blk-tabs1 .menu-btn").count() >= 2
