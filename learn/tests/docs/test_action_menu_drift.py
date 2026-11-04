"""menu.js's ENTRIES table must equal actions.menu_entries (allow_edit on)."""

import json
import re
from importlib.resources import files

from varde_learn.docs.pages.actions import BLOCK_TYPES, menu_entries
from varde_learn.docs.pages.template import page_scripts, static_scripts


def _menu_js() -> str:
    return (
        files("varde_learn.docs.pages").joinpath("static", "menu.js").read_text("utf-8")
    )


def _table() -> dict[str, list[str]]:
    found = re.search(r"export const ENTRIES = (\{.*?\});", _menu_js(), re.DOTALL)
    assert found, "menu.js has no ENTRIES constant"
    return json.loads(found.group(1))


def test_entries_table_matches_actions() -> None:
    expected = {
        block_type: list(
            menu_entries(block_type, allow_edit=True, in_part=block_type == "part")
        )
        for block_type in BLOCK_TYPES
    }
    assert _table() == expected


def test_code_block_offers_no_suggest() -> None:
    assert "suggest" not in _table()["code"]
    assert "comment" in _table()["code"]


def test_menu_is_an_es_module_loaded_by_import_not_a_tag() -> None:
    assert "menu.js" in static_scripts()
    assert "menu.js" not in page_scripts()


def test_menu_js_builds_nodes_without_html_parsing() -> None:
    forbidden = re.compile(
        r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\("
    )
    assert not forbidden.search(_menu_js())


def test_old_per_block_buttons_are_gone() -> None:
    app = (
        files("varde_learn.docs.pages").joinpath("static", "app.js").read_text("utf-8")
    )
    old = "|".join(f"{name}-btn" for name in ("comment", "suggest", "edit"))
    assert not re.search(old, app)


def test_decoration_only_blocks_get_no_menu() -> None:
    assert "export function hasContent" in _menu_js()
    assert "!hasContent(block)" in _menu_js()
