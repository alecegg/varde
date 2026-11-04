import pytest
from varde_learn.docs.pages.actions import (
    ALLOWED_KINDS,
    BLOCK_TYPES,
    component_block_type,
    kind_allowed,
    menu_entries,
)
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS

ROW_ENTRY_KIND = {"comment": "comment", "suggest": "suggestion"}
FLAGS = [(e, p) for e in (True, False) for p in (True, False)]


def test_every_type_has_kinds_and_comment():
    assert set(ALLOWED_KINDS) == set(BLOCK_TYPES)
    assert all(kind_allowed(t, "comment") for t in BLOCK_TYPES)


@pytest.mark.parametrize("block_type", ["prose", "heading", "list", "table"])
def test_text_types_allow_suggestion(block_type):
    assert kind_allowed(block_type, "suggestion")
    assert "suggest" in menu_entries(block_type, allow_edit=True, in_part=False)


@pytest.mark.parametrize(
    "block_type",
    ["code", "widget", "decision", "visual", "status", "part", "error"],
)
def test_other_types_refuse_suggestion(block_type):
    assert not kind_allowed(block_type, "suggestion")
    assert "suggest" not in menu_entries(block_type, allow_edit=True, in_part=False)


@pytest.mark.parametrize("allow_edit,in_part", FLAGS)
@pytest.mark.parametrize("block_type", BLOCK_TYPES)
def test_entries_write_only_accepted_kinds(block_type, allow_edit, in_part):
    entries = menu_entries(block_type, allow_edit=allow_edit, in_part=in_part)
    for entry, kind in ROW_ENTRY_KIND.items():
        if entry in entries:
            assert kind_allowed(block_type, kind)
    assert entries[0] == "comment" and entries[-1] == "copy-link"
    assert ("suggest" in entries) == (
        kind_allowed(block_type, "suggestion") and not in_part
    )
    assert ("edit" in entries) == (allow_edit and not in_part and block_type != "part")
    assert len(entries) <= 6


@pytest.mark.parametrize("block_type", BLOCK_TYPES)
def test_copy_presence(block_type):
    has = "copy" in menu_entries(block_type, allow_edit=True, in_part=False)
    assert has == (block_type not in {"widget", "decision", "status"})


def test_answer_only_on_widget_and_decision():
    assert {t for t in BLOCK_TYPES if kind_allowed(t, "answer")} == {
        "widget",
        "decision",
    }
    assert not kind_allowed("nonsense", "comment")


def test_every_component_maps_to_a_known_type():
    for name in COMPONENTS:
        assert component_block_type(name) in BLOCK_TYPES, name


@pytest.mark.parametrize(
    "component,expected",
    [
        ("choice", "widget"),
        ("form", "widget"),
        ("ranking", "widget"),
        ("slider", "widget"),
        ("comment", "widget"),
        ("decision", "decision"),
        ("code", "code"),
        ("include", "part"),
        ("recap", "status"),
        ("deps", "status"),
        ("chart", "visual"),
        ("diagram", "visual"),
        ("flow", "visual"),
        ("wireframe", "visual"),
        ("ui-states", "visual"),
        ("endpoint", "visual"),
        ("data-model", "visual"),
        ("table", "visual"),
        ("callout", "visual"),
        ("annotated-code", "visual"),
        ("file-tree", "visual"),
        ("unknown-thing", "error"),
    ],
)
def test_component_block_type(component, expected):
    assert component_block_type(component) == expected
