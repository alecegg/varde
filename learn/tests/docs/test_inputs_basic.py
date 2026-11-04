"""Input components `choice`, `form`, `comment` and the decision preset."""

from __future__ import annotations

import html
import json
import re
import threading
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages import blocks
from varde_learn.docs.pages.answers import answer_schema, validate_answer
from varde_learn.docs.pages.blocks.inputs import check_form_value
from varde_learn.docs.pages.blocks_render.decision import decision_as_choice
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.comments import comments_path, fold, read_rows
from varde_learn.docs.pages.serve import PageServer
from varde_learn.docs.pages.template import make_read_only

HOSTILE = '<script>alert(1)</script>"><img src=x onerror=alert(1)>'
DOC = (
    "# Plan\n\nBody.\n\n"
    "```ui\n"
    'pick = choice(question: "Which?", options: ["a", {"label": "B", '
    '"detail": "second", "value": "b"}])\n'
    'many = choice(question: "Which?", options: ["x", "y", "z"], multiple: true, '
    "comment: true)\n"
    'setup = form(fields: [{"name": "owner", "label": "Owner", "type": "text", '
    '"required": true, "maxlength": 5}, '
    '{"name": "n", "label": "N", "type": "number", "min": 1, "max": 10}, '
    '{"name": "region", "label": "Region", "type": "select", "options": ["eu", "us"]}, '
    '{"name": "ok", "label": "Ok", "type": "checkbox", "required": true}])\n'
    'note = comment(label: "Anything?")\n'
    "```\n\n"
    '```ui id=ship\nship = decision(question: "Ship?", '
    'options: ["approve", "deny", "comment"])\n```\n'
)
GOOD_FORM = {"owner": "ann", "n": 3, "region": "eu", "ok": True}


def rules(line: str) -> list[str]:
    return [e.rule for e in blocks.check(f"```ui\n{line}\n```\n")]


def test_examples_validate_and_help_names_options(capsys: Any) -> None:
    for name in ("choice", "form", "comment"):
        assert name in blocks.COMPONENT_SPECS
        assert name in COMPONENTS
    from varde_learn.docs.cli import run

    assert run(["blocks", "choice"]) == 0
    assert "options" in capsys.readouterr().out
    assert run(["blocks", "form"]) == 0
    assert "text|number|select|checkbox" in capsys.readouterr().out


def test_learn_check_accepts_the_document() -> None:
    assert blocks.check(DOC) == []


@pytest.mark.parametrize(
    ("line", "rule"),
    [
        ('c = choice(question: "Q", options: [])', "type"),
        ('c = choice(question: "Q", options: ["a", "a"])', "option-duplicate"),
        (
            'c = choice(question: "Q", options: [{"label": "A", "value": "b"}, "b"])',
            "option-duplicate",
        ),
        ('c = choice(question: "Q", options: ["a"], multiple: "yes")', "type"),
        ('c = choice(question: "Q", options: [{"detail": "d"}])', "missing-key"),
        ('c = choice(question: "Q", options: ["a\\u0007"])', "type"),
        ('c = choice(options: ["a"])', "missing-key"),
        ('c = choice(question: "Q", options: ["a"], extra: 1)', "unknown-key"),
        ('c = comment(label: "L", extra: 1)', "unknown-key"),
        ("c = comment()", "missing-key"),
        ('f = form(fields: [{"name": "A b", "label": "L", "type": "text"}])', "type"),
        ('f = form(fields: [{"name": "a", "label": "L", "type": "date"}])', "type"),
        (
            'f = form(fields: [{"name": "a", "label": "L", "type": "select"}])',
            "missing-key",
        ),
        (
            (
                'f = form(fields: [{"name": "a", "label": "L", "type": "number", '
                '"min": 5, "max": 1}])'
            ),
            "range",
        ),
        (
            'f = form(fields: [{"name": "a", "label": "L", "type": "text", "min": 1}])',
            "unknown-key",
        ),
        (
            (
                'f = form(fields: [{"name": "a", "label": "L", "type": "text"}, '
                '{"name": "a", "label": "M", "type": "text"}])'
            ),
            "field-duplicate",
        ),
    ],
)
def test_props_faults(line: str, rule: str) -> None:
    assert rule in rules(line)


def _doc_with(widget: str) -> str:
    return f"# P\n\n```ui\n{widget}\n```\n"


def render(name: str, props: dict[str, object], block_id: str = "w") -> str:
    return COMPONENTS[name].render(props, block_id)


class _Attributes(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.bad: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.bad += [n for n, _ in attrs if n.startswith("on") or n == "style"]


def _bad_attributes(markup: str) -> list[str]:
    parser = _Attributes()
    parser.feed(markup)
    return parser.bad


def test_choice_html_is_escaped_with_whitelisted_props() -> None:
    out = render(
        "choice",
        {
            "question": HOSTILE,
            "options": [{"label": HOSTILE, "detail": HOSTILE, "value": HOSTILE}],
            "multiple": True,
        },
    )
    assert "<script" not in out and "<img" not in out
    assert not _bad_attributes(out)
    attr = re.search(r'data-props="([^"]*)"', out)
    assert attr and json.loads(html.unescape(attr.group(1))) == {
        "multiple": True,
        "comment": False,
    }
    assert 'type="checkbox"' in out and 'data-component="choice"' in out


def test_form_html_has_typed_controls_and_client_keys_only() -> None:
    props: dict[str, object] = {
        "fields": [
            {"name": "n", "label": "N", "type": "number", "min": 1, "max": 9},
            {"name": "r", "label": "R", "type": "select", "options": ["a", HOSTILE]},
            {"name": "t", "label": HOSTILE, "type": "text", "maxlength": 5},
        ]
    }
    out = render("form", props)
    assert '<input type="number" step="any"' in out and 'min="1"' in out
    assert "<select " in out and "<img" not in out and "<script" not in out
    attr = html.unescape(re.search(r'data-props="([^"]*)"', out).group(1))  # type: ignore[union-attr]
    sent = json.loads(attr)["fields"]
    assert sent[1] == {"name": "r", "type": "select"}  # options stay server-side
    assert sent[0] == {"name": "n", "type": "number", "min": 1, "max": 9}


def test_make_read_only_disables_every_input_widget() -> None:
    out = make_read_only(
        render("form", json.loads(json.dumps(_form_props())))
        + render("choice", {"question": "Q", "options": ["a"], "comment": True})
        + render("comment", {"label": "L"})
    )
    for tag in ("button", "input", "select", "textarea"):
        assert f"<{tag} " not in out.replace(f"<{tag} disabled ", "")
    assert "disabled" in out


def _form_props() -> dict[str, object]:
    return {
        "fields": [
            {"name": "t", "label": "T", "type": "text"},
            {"name": "s", "label": "S", "type": "select", "options": ["a"]},
            {"name": "c", "label": "C", "type": "checkbox"},
        ]
    }


# ---- answers ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("item", "value", "text"),
    [
        ("pick", "a", ""),
        ("pick", "b", ""),  # the second option's `value`, not its label
        ("many", ["x", "z"], "why"),
        ("many", ["x", "y", "z"], ""),
        ("setup", {**GOOD_FORM, "region": ""}, ""),  # blank optional select
        ("setup", GOOD_FORM, ""),
        ("setup", {**GOOD_FORM, "n": None}, ""),
        ("note", "commented", "hello"),
        ("ship", "approved", ""),
    ],
)
def test_validate_answer_accepts(item: str, value: object, text: str) -> None:
    validate_answer(DOC, item, value, text)


@pytest.mark.parametrize(
    ("item", "value", "text"),
    [
        ("pick", "B", ""),  # the label is not the value
        ("pick", ["a"], ""),
        ("pick", "a", "text"),  # no `comment` prop, so no text
        ("pick", "a\x00", ""),
        ("many", ["x", "q"], ""),
        ("many", "x", ""),
        ("many", [], ""),  # a picked set holds at least one member
        ("many", ["x", "x"], ""),  # and each member once
        ("pick", "", ""),
        ("many", ["x"], "bad\x1b[2J"),
        ("note", "commented", ""),
        ("note", "other", "hello"),
        ("setup", {**GOOD_FORM, "extra": 1}, ""),
        ("setup", {"owner": "ann"}, ""),
        ("setup", {**GOOD_FORM, "owner": ""}, ""),  # required
        ("setup", {**GOOD_FORM, "owner": "toolong"}, ""),  # maxlength 5
        ("setup", {**GOOD_FORM, "owner": "a\x07"}, ""),
        ("setup", {**GOOD_FORM, "n": 0}, ""),  # below min
        ("setup", {**GOOD_FORM, "n": 11}, ""),  # above max
        ("setup", {**GOOD_FORM, "n": float("nan")}, ""),
        ("setup", {**GOOD_FORM, "n": float("inf")}, ""),
        ("setup", {**GOOD_FORM, "n": 10**400}, ""),
        ("setup", {**GOOD_FORM, "n": True}, ""),
        ("setup", {**GOOD_FORM, "n": "3"}, ""),
        ("setup", {**GOOD_FORM, "region": "asia"}, ""),
        ("setup", {**GOOD_FORM, "ok": False}, ""),  # required checkbox
        ("setup", {**GOOD_FORM, "ok": "yes"}, ""),
        ("setup", ["owner"], ""),
        ("missing", "a", ""),
    ],
)
def test_validate_answer_rejects(item: str, value: object, text: str) -> None:
    with pytest.raises(ValueError):
        validate_answer(DOC, item, value, text)


def test_form_value_check_reports_the_field() -> None:
    fields = (
        {"name": "n", "label": "N", "type": "number", "min": 1, "required": True},
    )
    with pytest.raises(ValueError, match="'n'"):
        check_form_value(fields, {"n": None})


def test_invalid_props_are_not_answerable() -> None:
    doc = _doc_with('c = choice(question: "Q", options: ["a", "a"])')
    assert answer_schema(doc, "c") is None


def test_decision_is_a_choice_preset_and_old_rows_still_validate() -> None:
    props = {"question": "Ship?", "options": ["approve", "comment"]}
    as_choice = decision_as_choice(props)
    assert as_choice["options"] == [
        {"label": "Approve", "value": "approved"},
        {"label": "Comment", "value": "commented"},
    ]
    assert as_choice["comment"] is True
    schema = answer_schema(DOC, "ship")
    assert schema is not None and schema.allowed == ("approved", "denied", "commented")
    with pytest.raises(ValueError):
        validate_answer(DOC, "ship", "commented", "")  # a comment needs text
    in_ui = _doc_with('go = decision(question: "Go?", options: ["deny"])')
    validate_answer(in_ui, "go", "denied", "")
    with pytest.raises(ValueError):
        validate_answer(in_ui, "go", "approved", "")


# ---- browser ----------------------------------------------------------------


@pytest.fixture
def site(tmp_path: Path) -> Iterator[tuple[PageServer, Path]]:
    doc = tmp_path / "plan.md"
    doc.write_text(DOC)
    server = PageServer(doc, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, doc
    server.shutdown()
    server.server_close()
    thread.join(5)


@pytest.fixture(scope="module")
def shared_page(browser_session: Any) -> Any:
    page = browser_session.new_page()
    page.set_default_timeout(10_000)
    return page


def _mount(page: Any, markup: str) -> None:
    # a widget block: only blocks that take answers accept one
    anchor = page.locator(".block[data-block-type='widget']").first.get_attribute(
        "data-anchor"
    )
    page.evaluate(
        """([markup, anchor]) => {
            const holder = document.createElement('template');
            holder.innerHTML = markup;
            const block = document.createElement('div');
            block.className = 'block';
            block.dataset.anchor = anchor;
            block.append(holder.content);
            document.querySelector('main[data-role="page"]').append(block);
        }""",
        [markup, anchor],
    )


def _answers(doc: Path) -> list[dict[str, Any]]:
    return [r for r in fold(read_rows(doc)) if r.get("kind") == "answer"]


@pytest.mark.slow
def test_browser_choice_form_and_comment_post_answer_rows(
    shared_page: Any, site: tuple[PageServer, Path]
) -> None:
    server, doc = site
    page = shared_page
    dialogs: list[str] = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    page.route("**/events", lambda route: route.abort())  # no live refresh
    page.goto(f"http://127.0.0.1:{server.port}/")
    page.wait_for_selector("main[data-role='page'] .block")
    page.wait_for_timeout(300)
    page.wait_for_selector(".comment[data-hydrated]")

    page.locator(".choice-send").first.click()  # nothing picked yet
    assert "Pick an option" in page.locator(".choice-error").first.inner_text()
    page.get_by_text("B", exact=True).click()
    page.locator(".choice-send").first.click()
    page.wait_for_function(
        "() => document.querySelector('.choice-state').textContent === 'Sent'"
    )

    many = page.locator(".choice").nth(1)
    many.get_by_text("x", exact=True).click()
    many.get_by_text("z", exact=True).click()
    many.locator(".choice-text").fill(HOSTILE)
    many.locator(".choice-send").click()
    many.locator(".choice-state", has_text="Sent").wait_for()

    form = page.locator(".form")
    form.locator("[data-field='owner']").fill("ann")
    form.locator("[data-field='n']").fill("11")
    form.locator(".form-send").click()
    assert "above 10" in form.locator(".form-error").inner_text()
    form.locator("[data-field='n']").fill("4")
    form.locator("[data-field='region']").select_option("eu")
    form.locator("[data-field='ok']").check()
    form.locator(".form-send").click()
    form.locator(".form-state", has_text="Sent").wait_for()

    note = page.locator(".comment")
    note.locator(".comment-send").click()
    assert "needs text" in note.locator(".comment-error").inner_text()
    note.locator(".comment-text").fill("fine")
    note.locator(".comment-send").click()
    note.locator(".comment-state", has_text="Sent").wait_for()

    got = {r["item"]: (r["value"], r.get("text", "")) for r in _answers(doc)}
    assert got["pick"][0] == "b"
    assert got["many"] == (["x", "z"], HOSTILE)
    assert got["setup"][0] == {"owner": "ann", "n": 4, "region": "eu", "ok": True}
    assert got["note"] == ("commented", "fine")
    assert page.locator("img").count() == 0 and dialogs == []
    assert comments_path(doc).exists()


def _setup_props() -> dict[str, object]:
    return {
        "fields": [
            {
                "name": "owner",
                "label": "Owner",
                "type": "text",
                "required": True,
                "maxlength": 5,
            },
            {"name": "n", "label": "N", "type": "number", "min": 1, "max": 10},
            {
                "name": "region",
                "label": "Region",
                "type": "select",
                "options": ["eu", "us"],
            },
            {"name": "ok", "label": "Ok", "type": "checkbox", "required": True},
        ]
    }


def test_check_refuses_a_form_whose_answer_could_not_fit() -> None:
    fields = ", ".join(
        f'{{"name": "f{i}", "label": "L", "type": "text", "maxlength": 600}}'
        for i in range(30)
    )
    assert "size" in rules(f"w = form(fields: [{fields}])")


def test_a_maximal_form_that_passes_check_is_accepted_by_validate_answer() -> None:
    names = [f"f{i}" for i in range(6)]
    fields = ", ".join(
        f'{{"name": "{n}", "label": "L", "type": "text", "maxlength": 600}}'
        for n in names
    )
    doc = _doc_with(f"w = form(fields: [{fields}])")
    assert blocks.check(doc) == []
    for worst in ('"' * 600, "\\" * 600, "\u00e9" * 600):  # escapes, non-ASCII
        validate_answer(doc, "w", dict.fromkeys(names, worst), "")


def test_required_select_refuses_the_blank_choice() -> None:
    doc = _doc_with(
        'w = form(fields: [{"name": "r", "label": "R", "type": "select", '
        '"options": ["a"], "required": true}])'
    )
    validate_answer(doc, "w", {"r": "a"}, "")
    with pytest.raises(ValueError):
        validate_answer(doc, "w", {"r": ""}, "")


def test_markup_has_group_semantics_blank_option_and_limits() -> None:
    choice = render("choice", {"question": "Q?", "options": ["a"], "comment": True})
    assert (
        "<fieldset" in choice and "<legend" in choice and 'maxlength="8000"' in choice
    )
    form = render(
        "form",
        _form_props()
        | {
            "fields": [
                {
                    "name": "s",
                    "label": "S",
                    "type": "select",
                    "options": ["a"],
                    "required": True,
                }
            ]
        },
    )
    assert '<option value=""></option>' in form and 'aria-required="true"' in form
    assert 'id="form-error-w"' in form


@pytest.mark.slow
def test_browser_focus_fieldset_hostile_props_and_read_only(
    shared_page: Any, site: tuple[PageServer, Path]
) -> None:
    server, doc = site
    page = shared_page
    page.route("**/events", lambda route: route.abort())
    page.goto(f"http://127.0.0.1:{server.port}/")
    page.wait_for_selector("main[data-role='page'] .block")
    pick = page.locator(".choice", has=page.locator("[data-item='pick']"))
    page.wait_for_selector(".form[data-hydrated]")

    assert pick.locator("fieldset legend").inner_text() == "Which?"
    pick.locator(".choice-send").click()
    assert page.evaluate("document.activeElement.type") == "radio"
    page.locator("[data-field='owner']").fill("")
    page.locator(".form-send").click()
    owner = page.locator("[data-field='owner']")
    assert page.evaluate("document.activeElement.dataset.field") == "owner"
    assert owner.get_attribute("aria-describedby").split()[-1] == "form-error-setup"
    assert owner.get_attribute("aria-required") == "true"

    # a successful send shows Sent; the next edit clears it; a second send posts again
    pick.get_by_text("a", exact=True).click()
    pick.locator(".choice-send").click()
    pick.locator(".choice-state", has_text="Sent").wait_for()
    pick.get_by_text("B", exact=True).click()
    page.wait_for_function(
        "() => document.querySelector('[data-item=pick] .choice-state')"
        ".textContent === ''"
    )
    pick.locator(".choice-send").click()
    pick.locator(".choice-state", has_text="Sent").wait_for()
    assert [r["value"] for r in _answers(doc) if r["item"] == "pick"] == ["a", "b"]

    # hostile data-props: a `__proto__` field name rejects the whole list
    hostile = html.escape(
        json.dumps({"fields": [{"name": "__proto__", "type": "text"}]}), quote=True
    )
    page.evaluate(
        """(markup) => {
            const holder = document.createElement('template');
            holder.innerHTML = markup;
            document.querySelector('.block').append(holder.content);
        }""",
        f'<div class="vb form" data-component="form" data-props="{hostile}">'
        '<form class="form-item" data-item="evil"><input data-field="__proto__">'
        '<button type="submit" class="evil-send">x</button>'
        '<span class="form-state"></span><p class="form-error"></p></form></div>',
    )
    page.locator("[data-props] .evil-send").click()
    assert page.evaluate("({}).polluted") is None
    assert not [r for r in _answers(doc) if r["item"] == "evil"]

    # read-only markup stays disabled after the runtime runs a send
    _mount(page, make_read_only(render("comment", {"label": "L"}, "note")))
    page.wait_for_selector(".comment[data-hydrated]")
    page.evaluate(
        """() => {
            const box = document.querySelectorAll('.comment-text')[1];
            box.value = 'hello';
            document.querySelectorAll('.comment-item')[1].requestSubmit();
        }"""
    )
    page.locator(".comment-state", has_text="Sent").first.wait_for()
    assert page.locator(".comment-text").nth(1).is_disabled()
    assert page.locator(".comment-send").nth(1).is_disabled()
