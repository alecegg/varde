"""Host component runtime: hostile props, text and answers never become code."""

from __future__ import annotations

import html
import json
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.assemble import assemble_static
from varde_learn.docs.pages.blocks.statement import statement_text
from varde_learn.docs.pages.render import classify_url, render_page
from varde_learn.docs.pages.serve import PageServer

VECTORS = json.loads(
    (Path(__file__).parent / "fixtures/url-vectors.json").read_text(encoding="utf-8")
)
STATIC = Path(__file__).parents[2] / "src/varde_learn/docs/pages/static"
HOSTILE = '<script>alert(1)</script>"><img src=x onerror=alert(1)>'
JS_URL = "javascript:alert(1)"
DECISION = statement_text(
    "d",
    "decision",
    {
        "question": HOSTILE,
        "options": ["approve", "deny", "comment"],
        "diff": HOSTILE,
        "evidence": [{"label": HOSTILE, "text": JS_URL}],
    },
)
DOC = f"# Plan\n\nBody [x]({JS_URL}) {HOSTILE}\n\n```ui id=d\n{DECISION}\n```\n"
EXECUTABLE = [
    r"<script(?![^>]*src=\"/static/)",
    r"<img",
    r"<[^>]*\son[a-z]+=",
    r"style=",
]
FORBIDDEN_JS = re.compile(
    r"eval\(|new Function|innerHTML|outerHTML|insertAdjacentHTML|document\.write"
    r"|setAttribute\(.on"
)


def assert_inert(html_text: str) -> None:
    for pattern in EXECUTABLE:
        assert not re.search(pattern, html_text), pattern
    assert not re.search(r'href="javascript:', html_text, re.IGNORECASE)


def test_rendered_and_exported_html_has_no_executable_form(tmp_path: Path) -> None:
    doc = tmp_path / "plan.md"
    doc.write_text(DOC)
    assert_inert(render_page(DOC, "plan.md").body)
    exported = assemble_static(doc)
    assert_inert(exported)
    assert "<script" not in exported


def test_static_scripts_have_no_dynamic_code_paths() -> None:
    for path in sorted(STATIC.glob("*.js")):
        assert not FORBIDDEN_JS.search(path.read_text()), path.name


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
    page = browser_session.new_page()
    page.set_default_timeout(10_000)
    return page


PROBE = {
    "title": HOSTILE,
    "href": JS_URL,
    "extra": "dropped",
    "count": "not a number",
    "tags": ["a", HOSTILE],
}
SCHEMA = {"title": "string", "href": "url", "count": "number", "tags": "strings"}


@pytest.mark.slow
def test_browser_runs_no_script_and_whitelists_props(
    shared_page: Any, site: PageServer
) -> None:
    page = shared_page
    dialogs: list[str] = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    page.goto(f"http://127.0.0.1:{site.port}/")
    page.wait_for_selector(".decision-verdict")
    page.wait_for_timeout(300)
    result = page.evaluate(
        """([props, schema]) => {
            const el = document.createElement('div');
            el.setAttribute('data-props', JSON.stringify(props));
            return [window.varde.readProps(el, schema),
                    window.varde.safeUrl('javascript:alert(1)'),
                    window.varde.safeUrl(' java\\nscript:alert(1)'),
                    window.varde.safeUrl('https://example.com/a'),
                    window.varde.safeUrl('#frag'),
                    window.varde.safeUrl('docs/page.md')];
        }""",
        [PROBE, SCHEMA],
    )
    props, js, split, https, frag, rel = result
    assert props == {"title": HOSTILE, "tags": PROBE["tags"]}  # bad types dropped
    assert js is None and split is None
    assert (
        https == "https://example.com/a" and frag == "#frag" and rel == "docs/page.md"
    )
    assert page.locator("img").count() == 0
    assert dialogs == []


@pytest.mark.slow
def test_answer_text_is_escaped_in_page_and_post(
    shared_page: Any, site: PageServer
) -> None:
    page = shared_page
    dialogs: list[str] = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    page.goto(f"http://127.0.0.1:{site.port}/")
    page.wait_for_selector(".decision-verdict")
    page.locator('.decision-verdict[data-verdict="commented"]').click()
    page.locator(".decision-text").fill(HOSTILE)
    page.locator(".decision-send").click()
    page.wait_for_selector(".decision-item[data-verdict]")
    assert page.locator("img").count() == 0
    assert dialogs == []


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: repr(v["url"]))
def test_classify_url_vectors(vector: dict[str, str]) -> None:
    assert classify_url(vector["url"]) == vector["kind"]


@pytest.mark.slow
def test_browser_classify_url_matches_python_vectors(
    shared_page: Any, site: PageServer
) -> None:
    shared_page.goto(f"http://127.0.0.1:{site.port}/")
    shared_page.wait_for_selector(".decision-verdict")
    got = shared_page.evaluate(
        "(urls) => urls.map((u) => window.varde.classifyUrl(u))",
        [v["url"] for v in VECTORS],
    )
    assert got == [v["kind"] for v in VECTORS]
    safe = shared_page.evaluate(
        "(urls) => urls.map((u) => window.varde.safeUrl(u))",
        [v["url"] for v in VECTORS],
    )
    assert safe == [None if v["kind"] == "text" else v["url"] for v in VECTORS]


HYDRATE_PROPS = {"title": HOSTILE, "href": JS_URL, "ok": "docs/a.md", "n": "x"}


@pytest.mark.slow
def test_data_props_hydrates_through_whitelist(
    shared_page: Any, site: PageServer
) -> None:
    page = shared_page
    dialogs: list[str] = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    page.goto(f"http://127.0.0.1:{site.port}/")
    page.wait_for_selector(".decision-verdict")
    page.evaluate(
        """() => window.varde.register('probe', {
            props: { title: 'string', href: 'url', ok: 'url', n: 'number' },
            hydrate(element, props) {
                const label = document.createElement('span');
                label.textContent = props.title || '';
                element.append(label);
                element.dataset.keys = Object.keys(props).sort().join(',');
            },
        })"""
    )
    # Written the way the server must: html.escape(json, quote=True).
    attr = html.escape(json.dumps(HYDRATE_PROPS), quote=True)
    page.evaluate(
        """(markup) => {
            const holder = document.createElement('template');
            holder.innerHTML = markup;
            document.querySelector('main[data-role="page"]').append(holder.content);
        }""",
        f'<div class="probe" data-component="probe" data-props="{attr}"></div>',
    )
    probe = page.locator(".probe[data-hydrated]")
    probe.wait_for()
    assert probe.get_attribute("data-keys") == "ok,title"  # javascript: and n dropped
    assert probe.locator("span").inner_text() == HOSTILE
    assert page.locator("img").count() == 0
    assert dialogs == []
