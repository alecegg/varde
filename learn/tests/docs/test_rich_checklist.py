"""checklist: counts, state agreement, empty and large lists, escaping, registration."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks import check, check_props
from varde_learn.docs.pages.blocks_render.checklist import render_checklist
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.render import render_page

FIXTURES = Path(__file__).parent / "fixtures" / "widgets"


def rules_of(data: dict[str, Any]) -> list[str]:
    return [e.rule for e in check_props("checklist", data, 1)]


def test_count_text_and_progress_agree_with_the_items() -> None:
    items = [{"label": "a", "status": "done"}, {"label": "b", "checked": True}]
    out = render_checklist({"items": [*items, {"label": "c"}]})
    assert "2 of 3 done" in out
    assert 'value="2" max="3"' in out
    assert 'aria-label="Checklist, 2 of 3 done"' in out


def test_one_of_one_reads_correctly() -> None:
    out = render_checklist({"items": [{"label": "a", "status": "done"}]})
    assert "1 of 1 done" in out


def test_each_state_has_glyph_and_word() -> None:
    items = [{"label": s, "status": s} for s in ("done", "open", "blocked")]
    out = render_checklist({"items": items})
    for state, word in (("done", "Done"), ("open", "Open"), ("blocked", "Blocked")):
        assert f"vd-checklist-{state}" in out
        assert f"</span> {word}</span>" in out
    assert "<input" not in out


def test_items_default_to_open() -> None:
    assert "vd-checklist-open" in render_checklist({"items": [{"label": "a"}]})


def test_checked_and_status_conflict_is_a_fault() -> None:
    bad = {"items": [{"label": "a", "checked": True, "status": "open"}]}
    assert "conflict" in rules_of(bad)
    bad = {"items": [{"label": "a", "checked": False, "status": "done"}]}
    assert "conflict" in rules_of(bad)
    ok = {"label": "a", "checked": True, "status": "done"}
    assert rules_of({"items": [ok]}) == []
    ok = {"label": "a", "checked": False, "status": "blocked"}
    assert rules_of({"items": [ok]}) == []


def test_props_are_validated() -> None:
    assert rules_of({"items": [{"label": "a"}], "covers": ["x"]}) == []
    assert rules_of({}) == ["missing-key"]
    assert rules_of({"items": [{"note": "n"}]}) == ["missing-key"]
    assert rules_of({"items": [{"label": "a", "status": "later"}]})
    assert rules_of({"items": [{"label": "a", "checked": "yes"}]})
    assert rules_of({"items": [{"label": "a", "extra": 1}]})
    assert rules_of({"items": "a"})
    assert "limit" in rules_of({"items": [{"label": "a"}] * 501})


def test_empty_list_renders_zero_of_zero_and_a_nonzero_max() -> None:
    out = render_checklist({"items": []})
    assert "0 of 0 done" in out and 'max="1"' in out and "<ul" not in out


def test_two_hundred_items_and_long_labels_render() -> None:
    status = ["done", "open"]
    items = [{"label": "w" * 300, "status": status[i % 2]} for i in range(200)]
    out = render_checklist({"items": items})
    assert out.count("<li ") == 200 and "100 of 200 done" in out
    assert "w" * 300 in out


def test_hostile_text_is_escaped() -> None:
    out = render_checklist(
        {
            "title": "<b>t</b>",
            "items": [
                {"label": "<script>x</script> `<i>c</i>`", "note": "<img src=x>"}
            ],
        }
    )
    assert "<script>" not in out and "<b>t</b>" not in out and "<img" not in out
    assert "<code>&lt;i&gt;c&lt;/i&gt;</code>" in out
    assert "style=" not in out


def test_copy_text_is_a_markdown_task_list() -> None:
    out = render_checklist(
        {"title": "T", "items": [{"label": "a", "status": "done"}, {"label": "b"}]}
    )
    found = re.search(r'data-copy="([^"]*)"', out)
    assert found and html.unescape(found[1]) == "T\n- [x] a\n- [ ] b"


def test_root_has_the_component_class_and_a_text_alternative() -> None:
    out = render_checklist({"items": [{"label": "a"}]})
    assert 'class="vb checklist vd-checklist"' in out and 'class="vb-alt ' in out


def test_registered_and_fixtures_render() -> None:
    assert "checklist" in COMPONENTS
    for name in ("rich-checklist", "rich-checklist-stress"):
        doc = (FIXTURES / f"{name}.md").read_text()
        assert check(doc) == []
        body = render_page(doc, "t.md").body
        assert "vb-error" not in body and "<img" not in body
        assert "<script>alert" not in body and "style=" not in body
        assert "vd-checklist" in body


@pytest.mark.parametrize("name", ["rich-checklist", "rich-checklist-stress"])
def test_fixture_family_exists(name: str) -> None:
    assert (FIXTURES / f"{name}.md").exists()
