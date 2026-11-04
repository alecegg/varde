"""Input components `ranking` and `slider`."""

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
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.comments import fold, read_rows
from varde_learn.docs.pages.serve import PageServer
from varde_learn.docs.pages.template import make_read_only

HOSTILE = '<script>alert(1)</script>"><img src=x onerror=alert(1)>'
DOC = (
    "# Plan\n\nBody.\n\n"
    "```ui\n"
    'order = ranking(question: "Urgency?", items: ["a", {"label": "B", '
    '"detail": "second", "value": "b"}, "c"])\n'
    'conf = slider(label: "Confidence", min: 0, max: 10, step: 2, '
    'labels: ["Low", "High"])\n'
    'frac = slider(label: "Share", min: 0, max: 1, step: 0.1)\n'
    'plain = slider(label: "Plain", min: -5, max: 5)\n'
    "```\n"
)


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


def rules(line: str) -> list[str]:
    return [e.rule for e in blocks.check(f"```ui\n{line}\n```\n")]


def render(name: str, props: dict[str, object], block_id: str = "w") -> str:
    return COMPONENTS[name].render(props, block_id)


def _doc_with(widget: str) -> str:
    return f"# P\n\n```ui\n{widget}\n```\n"


def test_document_validates_and_help_names_the_step(capsys: Any) -> None:
    from varde_learn.docs.cli import run

    assert blocks.check(DOC) == []
    assert run(["blocks", "slider"]) == 0
    assert "step" in capsys.readouterr().out
    assert run(["blocks", "ranking"]) == 0
    assert "items" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("line", "rule"),
    [
        ('r = ranking(question: "Q", items: ["a"])', "type"),  # needs two
        ('r = ranking(question: "Q", items: ["a", "a"])', "option-duplicate"),
        (
            'r = ranking(question: "Q", items: [{"label": "A", "value": "b"}, "b"])',
            "option-duplicate",
        ),
        ('r = ranking(items: ["a", "b"])', "missing-key"),
        (
            'r = ranking(question: "Q", items: ["a", "b"], multiple: true)',
            "unknown-key",
        ),
        ('r = ranking(question: "Q", items: ["a", "b\\u0007"])', "type"),
        ('s = slider(label: "L", max: 5)', "missing-key"),
        ('s = slider(label: "L", min: 5, max: 1)', "range"),
        ('s = slider(label: "L", min: 1, max: 1)', "range"),
        ('s = slider(label: "L", min: 0, max: 5, step: 0)', "range"),
        ('s = slider(label: "L", min: 0, max: 5, step: -1)', "range"),
        ('s = slider(label: "L", min: 0, max: 5, step: 9)', "range"),
        ('s = slider(label: "L", min: 0, max: 1000000, step: 1)', "range"),
        ('s = slider(label: "L", min: "a", max: 5)', "type"),
        ('s = slider(label: "L", min: 0, max: 5, labels: ["x"])', "type"),
        ('s = slider(label: "L", min: 0, max: 5, labels: ["x", ""])', "type"),
        ('s = slider(label: "L", min: 0, max: 5, extra: 1)', "unknown-key"),
    ],
)
def test_props_faults(line: str, rule: str) -> None:
    assert rule in rules(line)


def test_check_refuses_a_ranking_whose_answer_could_not_fit() -> None:
    items = ", ".join(f'"{chr(97 + i % 26) * 300}{i}"' for i in range(30))
    assert "size" in rules(f'r = ranking(question: "Q", items: [{items}])')


def test_a_maximal_ranking_that_passes_check_is_accepted_by_validate_answer() -> None:
    values = ['"' * 300 + str(i) for i in range(10)]
    items = json.dumps(values)
    doc = _doc_with(f'r = ranking(question: "Q", items: {items})')
    assert blocks.check(doc) == []
    validate_answer(doc, "r", values[::-1], "")


@pytest.mark.parametrize(
    ("item", "value"),
    [
        ("order", ["a", "b", "c"]),
        ("order", ["c", "a", "b"]),  # `b` is the second item's value, not its label
        ("conf", 0),
        ("conf", 10),
        ("conf", 4.0),
        ("conf", 6),
        ("frac", 0.3),  # float steps: 0.1 * 3
        ("frac", 0.7),
        ("frac", 1),
        ("plain", -5),
        ("plain", -2),
    ],
)
def test_validate_answer_accepts(item: str, value: object) -> None:
    validate_answer(DOC, item, value, "")


@pytest.mark.parametrize(
    ("item", "value"),
    [
        ("order", ["a", "b"]),  # missing one
        ("order", ["a", "b", "c", "c"]),  # extra
        ("order", ["a", "a", "b"]),  # repeated
        ("order", ["a", "b", "z"]),  # unknown
        ("order", ["a", "B", "c"]),  # label, not value
        ("order", []),
        ("order", "a"),
        ("order", ["a", "b", 3]),
        ("order", ["a", "b", "c\x00"]),
        ("conf", 11),
        ("conf", -1),
        ("conf", 3),  # off the step of 2
        ("conf", 4.5),
        ("conf", True),
        ("conf", "4"),
        ("conf", None),
        ("conf", float("nan")),
        ("conf", float("inf")),
        ("conf", -float("inf")),
        ("conf", 10**400),
        ("frac", 0.35),
        ("frac", 1.1),
        ("plain", 5.5),
        ("order", 3),
    ],
)
def test_validate_answer_rejects(item: str, value: object) -> None:
    with pytest.raises(ValueError):
        validate_answer(DOC, item, value, "")


def test_ranking_and_slider_take_no_text() -> None:
    with pytest.raises(ValueError, match="takes no text"):
        validate_answer(DOC, "conf", 4, "why")
    with pytest.raises(ValueError, match="takes no text"):
        validate_answer(DOC, "order", ["a", "b", "c"], "why")


def test_schemas_carry_the_declared_range_and_items() -> None:
    schema = answer_schema(DOC, "conf")
    assert schema is not None and schema.bounds == (0, 10, 2)
    schema = answer_schema(DOC, "plain")
    assert schema is not None and schema.bounds == (-5, 5, 1)
    ranking = answer_schema(DOC, "order")
    assert ranking is not None and ranking.allowed == ("a", "b", "c")


def test_invalid_props_are_not_answerable() -> None:
    doc = _doc_with('s = slider(label: "L", min: 5, max: 1)')
    assert answer_schema(doc, "s") is None


# ---- markup -----------------------------------------------------------------


def _attrs(out: str) -> dict[str, object]:
    found = re.search(r'data-props="([^"]*)"', out)
    assert found
    return json.loads(html.unescape(found.group(1)))


def test_ranking_markup_is_escaped_grouped_and_has_move_buttons() -> None:
    out = render(
        "ranking",
        {
            "question": HOSTILE,
            "items": [
                {"label": HOSTILE, "detail": HOSTILE, "value": HOSTILE},
                "b",
            ],
        },
    )
    assert "<script" not in out and "<img" not in out
    assert not _bad_attributes(out)
    assert "<fieldset" in out and "<legend" in out and "<ol " in out
    assert out.count('class="ranking-move"') == 4
    assert 'aria-label="Move b up"' in out and 'aria-label="Move b down"' in out
    assert 'role="status"' in out and 'id="ranking-error-w"' in out
    assert _attrs(out) == {}


def test_slider_markup_has_native_range_with_bounds_and_whitelisted_props() -> None:
    out = render(
        "slider",
        {"label": HOSTILE, "min": 0, "max": 10, "step": 2, "labels": [HOSTILE, "H"]},
    )
    assert '<input type="range"' in out and 'min="0"' in out and 'step="2"' in out
    assert "<script" not in out and "<img" not in out
    assert not _bad_attributes(out)
    assert "<fieldset" in out and "<legend" in out and 'aria-label="' in out
    assert _attrs(out) == {"min": 0, "max": 10, "step": 2}
    assert 'id="slider-error-w"' in out


def test_make_read_only_disables_ranking_and_slider() -> None:
    out = make_read_only(
        render("ranking", {"question": "Q", "items": ["a", "b"]})
        + render("slider", {"label": "L", "min": 0, "max": 3})
    )
    for tag in ("button", "input"):
        assert f"<{tag} " not in out.replace(f"<{tag} disabled ", "")
    assert "disabled" in out


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
    anchor = page.locator(".block").first.get_attribute("data-anchor")
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


def _open(page: Any, server: PageServer) -> None:
    page.route("**/events", lambda route: route.abort())
    page.goto(f"http://127.0.0.1:{server.port}/")
    page.wait_for_selector("main[data-role='page'] .block")
    page.wait_for_timeout(300)


@pytest.mark.slow
def test_browser_ranking_buttons_drag_and_announcement(
    shared_page: Any, site: tuple[PageServer, Path]
) -> None:
    server, doc = site
    page = shared_page
    _open(page, server)
    page.wait_for_selector(".ranking[data-hydrated]")

    # keyboard path: focus the move-down button of `a` and press Enter
    page.locator("[aria-label='Move a down']").focus()
    page.keyboard.press("Enter")
    page.locator(".ranking-live", has_text="a is at position 2 of 3.").wait_for()
    row_display = page.eval_on_selector(
        ".ranking-row", "r => getComputedStyle(r).display"
    )
    assert row_display == "list-item"  # keeps the numbered marker
    assert (
        page.evaluate("document.activeElement.getAttribute('aria-label')")
        == "Move a down"
    )
    page.keyboard.press("Enter")
    page.locator("[aria-label='Move c up']").click()
    ids = page.eval_on_selector_all(
        ".ranking-row", "rows => rows.map(r => r.dataset.id)"
    )
    assert ids == ["c", "b", "a"]  # a moved down twice, then c up one
    box = page.locator(".ranking-move").first.bounding_box()
    assert box["width"] >= 44 and box["height"] >= 44

    # at the end of the list a repeated press still announces, with a changed text
    page.locator("[aria-label='Move a down']").click()
    page.locator(".ranking-live", has_text="Already last.").wait_for()
    page.locator("[aria-label='Move a down']").click()
    page.locator(".ranking-live", has_text="Already last.").wait_for()
    page.locator("[aria-label='Move a up']").click()
    page.locator("[aria-label='Move B (b) up']").click()
    assert page.eval_on_selector_all(
        ".ranking-row", "r => r.map(x => x.dataset.id)"
    ) == ["c", "b", "a"]

    # drag the last row above the first
    rows = page.locator(".ranking-row")
    first = page.eval_on_selector(".ranking-row", "r => r.dataset.id")
    rows.last.drag_to(rows.first)
    after = page.eval_on_selector_all(
        ".ranking-row", "rows => rows.map(r => r.dataset.id)"
    )
    assert sorted(after) == ["a", "b", "c"] and after[1] == first

    page.locator(".ranking-send").focus()
    page.keyboard.press("Enter")
    page.locator(".ranking-state", has_text="Sent").wait_for()
    assert page.evaluate("document.activeElement.className") == "ranking-send"
    # while controls are paused (a send in flight) a drag must not start
    cancelled = page.evaluate(
        """() => {
            const list = document.querySelector('.ranking-list');
            list.querySelector('.ranking-move').disabled = true;
            const event = new Event('dragstart', { bubbles: true, cancelable: true });
            list.firstElementChild.dispatchEvent(event);
            list.querySelector('.ranking-move').disabled = false;
            return event.defaultPrevented;
        }"""
    )
    assert cancelled
    sent = [r["value"] for r in _answers(doc) if r["item"] == "order"]
    assert sent == [after]


@pytest.mark.slow
def test_browser_slider_needs_a_move_then_posts_and_read_only_stays_inert(
    shared_page: Any, site: tuple[PageServer, Path]
) -> None:
    server, doc = site
    page = shared_page
    _open(page, server)
    conf = page.locator(".slider", has=page.locator("[data-item='conf']"))
    page.wait_for_selector(".slider[data-hydrated]")

    conf.locator(".slider-send").click()
    assert "Move the slider" in conf.locator(".slider-error").inner_text()
    assert page.evaluate("document.activeElement.type") == "range"
    assert (
        conf.locator(".slider-input").get_attribute("aria-describedby")
        == "slider-error-conf"
    )
    box = conf.locator(".slider-input").bounding_box()
    assert box["height"] >= 44

    conf.locator(".slider-input").focus()
    page.keyboard.press("Home")
    for _ in range(3):
        page.keyboard.press("ArrowRight")
    assert conf.locator(".slider-value").inner_text() == "6"
    conf.locator(".slider-send").click()
    conf.locator(".slider-state", has_text="Sent").wait_for()
    assert [r["value"] for r in _answers(doc) if r["item"] == "conf"] == [6]

    # hostile data-props: a missing range refuses to send and posts nothing
    bad = html.escape(json.dumps({"min": "x", "step": -1}), quote=True)
    page.evaluate(
        """(markup) => {
            const holder = document.createElement('template');
            holder.innerHTML = markup;
            document.querySelector('.block').append(holder.content);
        }""",
        f'<div class="vb slider" data-component="slider" data-props="{bad}">'
        '<form class="slider-item" data-item="evil">'
        '<input type="range" class="slider-input">'
        '<button type="submit" class="evil-send">x</button>'
        '<span class="slider-state"></span><p class="slider-error"></p></form></div>',
    )
    page.locator(".evil-send").click()
    assert not [r for r in _answers(doc) if r["item"] == "evil"]

    # read-only markup: controls stay disabled and the drag stays off
    _mount(
        page,
        make_read_only(render("ranking", {"question": "Q", "items": ["a", "b"]}, "ro")),
    )
    page.wait_for_selector(".ranking[data-hydrated]:has([data-item='ro'])")
    assert page.locator("[data-item='ro'] .ranking-move").first.is_disabled()
    drag = page.eval_on_selector_all(
        "[data-item='ro'] .ranking-row", "rows => rows.map(r => r.draggable)"
    )
    assert drag == [False, False]


# ---- review 01 fixes ----------------------------------------------------------


def test_large_magnitude_and_float_steps_are_on_step() -> None:
    doc = _doc_with(
        's = slider(label: "L", min: 1000000000000, max: 1000000000010, step: 0.001)'
    )
    assert blocks.check(doc) == []
    for good in (1e12, 1e12 + 0.001, 1e12 + 0.003, 1e12 + 10):
        validate_answer(doc, "s", good, "")
    with pytest.raises(ValueError, match="whole number of"):
        validate_answer(doc, "s", 1e12 + 0.0005, "")  # half a step off
    validate_answer(DOC, "frac", 0.30000000000000004, "")
    with pytest.raises(ValueError):
        validate_answer(DOC, "frac", 0.31, "")


def test_slider_rejections_name_the_range_or_the_step() -> None:
    with pytest.raises(ValueError, match="between 0 and 10"):
        validate_answer(DOC, "conf", 11, "")
    with pytest.raises(ValueError, match="whole number of 2"):
        validate_answer(DOC, "conf", 3, "")
    with pytest.raises(ValueError, match="number"):
        validate_answer(DOC, "conf", float("nan"), "")


def test_markup_wraps_the_flex_line_and_names_twins_and_unchosen_value() -> None:
    out = render(
        "ranking",
        {
            "question": "Q",
            "items": [{"label": "Same", "value": "x"}, {"label": "Same", "value": "y"}],
        },
    )
    assert 'class="ranking-row"' in out and 'class="ranking-line"' in out
    assert (
        'aria-label="Move Same (x) up"' in out
        and 'aria-label="Move Same (y) up"' in out
    )
    slider = render("slider", {"label": "L", "min": 0, "max": 3})
    assert 'aria-valuetext="Not chosen yet"' in slider


@pytest.mark.slow
def test_browser_missing_inputs_helpers_show_a_failure(
    shared_page: Any, site: tuple[PageServer, Path]
) -> None:
    from varde_learn.docs import pages

    server, _ = site
    page = shared_page
    source = (Path(pages.__file__).parent / "static" / "recap.js").read_text()
    stale = source.replace("inputs: Object.freeze({ sendAnswer, onSubmit, fail })", "")
    assert stale != source
    page.route(
        "**/static/recap.js",
        lambda route: route.fulfill(body=stale, content_type="text/javascript"),
    )
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    _open(page, server)
    page.locator(".slider-error", has_text="could not start").first.wait_for()
    assert any("inputs is missing" in e for e in errors)
    page.unroute("**/static/recap.js")


@pytest.mark.slow
def test_browser_slider_valuetext_starts_unchosen(
    shared_page: Any, site: tuple[PageServer, Path]
) -> None:
    server, _ = site
    page = shared_page
    _open(page, server)
    conf = page.locator(".slider", has=page.locator("[data-item='conf']"))
    page.wait_for_selector(".slider[data-hydrated]")
    assert (
        conf.locator(".slider-input").get_attribute("aria-valuetext")
        == "Not chosen yet"
    )
    conf.locator(".slider-input").focus()
    page.keyboard.press("Home")
    # the native value says the same, so the runtime drops aria-valuetext
    assert conf.locator(".slider-input").get_attribute("aria-valuetext") is None
    assert conf.locator(".slider-input").input_value() == "0"
