"""The change vocabulary on data-model and endpoint: enum, was, escaping, identity."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from varde_learn.docs.pages.blocks import check, check_props
from varde_learn.docs.pages.blocks.change import CHANGES, change_faults
from varde_learn.docs.pages.blocks_render.backend import (
    render_data_model,
    render_endpoint,
)
from varde_learn.docs.pages.blocks_render.change import (
    change_badge,
    copy_line,
)
from varde_learn.docs.pages.render import render_page

FIXTURES = Path(__file__).parent / "fixtures" / "widgets"
GLYPHS = {"added": "+", "modified": "~", "removed": "-", "renamed": "->"}
PLAIN_MODEL: dict[str, object] = {
    "entity": [
        {
            "name": "order",
            "key": "id",
            "fields": {"id": "uuid", "total": "cents"},
            "relations": [{"to": "order", "kind": "one-to-one"}],
        }
    ]
}
PLAIN_ENDPOINT: dict[str, object] = {
    "method": "GET",
    "path": "/x",
    "auth": "none",
    "request": {"q": "text"},
    "responses": [{"status": 200, "body": "ok"}],
}


def model_with(field: object) -> dict[str, object]:
    return {
        "entity": [{"name": "a", "key": "id", "fields": {"id": "uuid", "f": field}}]
    }


@pytest.mark.parametrize("change", CHANGES)
def test_each_marker_has_glyph_and_word(change: str) -> None:
    html = change_badge(change)
    assert f'aria-hidden="true">{GLYPHS[change].replace(">", "&gt;")}</span>' in html
    assert f"</span> {change}</span>" in html
    assert f"vd-change-{change}" in html


def test_was_is_escaped_and_shown_for_modified() -> None:
    html = change_badge("modified", "<b>old</b>")
    assert "&lt;b&gt;old&lt;/b&gt;" in html and "<b>" not in html
    assert "was" in html


def test_enum_and_was_rules() -> None:
    assert change_faults({"change": "added"}, "x") == []
    assert change_faults({"change": "renamed", "was": "a"}, "x") == []
    assert change_faults({"change": "modified", "was": "a"}, "x") == []
    unknown = change_faults({"change": "moved"}, "x")
    assert unknown and all(c in unknown[0].message for c in CHANGES)
    assert change_faults({"change": "renamed"}, "x")
    assert change_faults({"change": "removed", "was": "a"}, "x")
    assert change_faults({"was": "a"}, "x")
    assert change_faults({"change": "modified", "was": ""}, "x")


def test_spec_checks_every_place_a_change_can_sit() -> None:
    bad_field = model_with({"type": "text", "change": "renamed"})
    assert check_props("data-model", bad_field, 1)
    assert (
        check_props("data-model", model_with({"type": "t", "change": "added"}), 1) == []
    )
    assert check_props("data-model", model_with({"change": "added"}), 1)
    assert check_props("data-model", model_with(3), 1)
    entity = {"name": "a", "key": "id", "fields": {"id": "uuid"}, "change": "gone"}
    assert check_props("data-model", {"entity": [entity]}, 1)
    endpoint = {**PLAIN_ENDPOINT, "change": "removed", "was": "x"}
    assert check_props("endpoint", endpoint, 1)
    row = {"status": 200, "change": "renamed"}
    assert check_props("endpoint", {**PLAIN_ENDPOINT, "responses": [row]}, 1)
    request = {"q": {"type": "text", "change": "bad"}}
    assert check_props("endpoint", {**PLAIN_ENDPOINT, "request": request}, 1)


def test_documents_without_change_render_unchanged() -> None:
    model = render_data_model(PLAIN_MODEL)
    endpoint = render_endpoint(PLAIN_ENDPOINT)
    assert "vd-change" not in model + endpoint and "data-copy" not in model + endpoint
    assert model == (
        '<div class="vb data-model"><p class="vb-alt">1 entity, 1 relation</p>'
        '<div class="vb-grid"><section class="vb-card">'
        '<h4 class="vb-title">order</h4>'
        '<div class="vb-fields-scroll" role="region" aria-label="order fields" '
        'tabindex="0"><table class="vb-fields">'
        "<thead><tr><th>field</th><th>type</th>"
        '<th><span class="vb-sr">flags</span></th></tr></thead>'
        "<tbody><tr><td>id</td><td>uuid</td><td>"
        '<span class="vb-badge vb-badge-key">key</span></td></tr><tr><td>total</td>'
        "<td>cents</td><td></td></tr></tbody></table></div>"
        '<ul class="vb-relations"><li>&rarr; <strong>order</strong> '
        '<span class="vb-badge vb-rel">one-to-one</span></li></ul>'
        "</section></div></div>"
    )
    assert endpoint == (
        '<div class="vb endpoint">'
        '<p class="vb-alt">GET /x: auth none, 1 response</p>'
        '<section class="vb-card"><h4 class="vb-title">'
        '<span class="vb-badge vb-method">GET</span> <code>/x</code> '
        '<span class="vb-badge vb-auth-none">auth: none</span></h4>'
        '<div class="vb-fields-scroll" role="region" aria-label="Request" '
        'tabindex="0"><table class="vb-fields"><thead><tr><th>request</th>'
        "<th>type</th></tr></thead>"
        "<tbody><tr><td>q</td><td>text</td></tr></tbody></table></div>"
        '<div class="vb-fields-scroll" role="region" aria-label="Responses" '
        'tabindex="0"><table class="vb-fields"><thead><tr><th>status</th>'
        "<th>body</th></tr></thead>"
        '<tbody><tr><td><span class="vb-badge vb-status">200</span></td>'
        "<td>ok</td></tr></tbody></table></div></section></div>"
    )


def test_renamed_field_shows_old_and_new_and_row_name_has_the_word() -> None:
    field = {"type": "text", "change": "renamed", "was": "name"}
    html = render_data_model(model_with(field))
    assert re.search(r'vd-change-old">name</span> &rarr; <span[^>]*>f</span>', html)
    assert 'aria-label="renamed f"' in html
    assert "</span> renamed</span>" in html


def test_removed_field_stays_readable() -> None:
    html = render_data_model(model_with({"type": "text", "change": "removed"}))
    assert "vd-change-removed" in html and "</span> removed</span>" in html
    assert "<td>text</td>" in html


def test_copy_text_lists_each_changed_row() -> None:
    assert copy_line("renamed", "a.f", "name") == "renamed a.f (was name)"
    assert copy_line("added", "a.f", "") == "added a.f"
    field = {"type": "text", "change": "renamed", "was": "name"}
    html = render_data_model(model_with(field))
    assert 'data-copy="renamed a.f (was name)"' in html
    endpoint = {
        **PLAIN_ENDPOINT,
        "change": "modified",
        "was": "GET /y",
        "responses": [{"status": 404, "change": "added"}],
    }
    html = render_endpoint(endpoint)
    assert "modified GET /x (was GET /y)\nadded response 404" in html


def test_hostile_was_and_names_are_escaped() -> None:
    field = {"type": "<i>t</i>", "change": "modified", "was": "<script>x</script>"}
    html = render_data_model(model_with(field))
    assert "<script>" not in html and "<i>" not in html and "style=" not in html
    assert "&lt;script&gt;" in html


def test_two_hundred_changed_fields_each_get_a_marker() -> None:
    fields = {f"f{i}": {"type": "t", "change": "added"} for i in range(200)}
    html = render_data_model({"entity": [{"name": "a", "key": "f0", "fields": fields}]})
    assert html.count("vd-change-row") == 200
    assert html.count("</span> added</span>") == 200


@pytest.mark.parametrize("name", ["rich-change.md", "rich-change-stress.md"])
def test_fixtures_validate_and_render_without_errors(name: str) -> None:
    doc = (FIXTURES / name).read_text()
    assert check(doc) == []
    body = render_page(doc, "t.md").body
    assert "vb-error" not in body and "vd-change-" in body
    assert "<img" not in body and "<script>alert" not in body and "style=" not in body
