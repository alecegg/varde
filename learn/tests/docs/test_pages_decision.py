"""Decision block: render, escaping, answer rows, remote gate, one-click buttons."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages import remote
from varde_learn.docs.pages.comments import append_reply, fold, read_rows
from varde_learn.docs.pages.render import render_page
from varde_learn.docs.pages.serve import PageServer

from .ui_fence import ui_fence

HOSTILE = "<script>alert(1)</script>"
BLOCK = (
    'question = "Ship the change?"\n'
    'options = ["approve", "deny", "comment"]\n'
    'diff = "- old\\n+ new"\n'
    '[[evidence]]\nlabel = "friction"\ntext = "3 sessions"\n'
)
ONLY = 'question = "Only approve?"\noptions = ["approve"]\n'
DOC = (
    f"# Plan\n\nBody.\n\n{ui_fence('decision', BLOCK, 'ship')}\n"
    f"{ui_fence('decision', ONLY, 'only')}"
)


def start(tmp_path: Path, *, remote_policy: bool = False, allow_edit: bool = False):
    doc = tmp_path / "plan.md"
    doc.write_text(DOC, encoding="utf-8")
    server = PageServer(doc, 0, "127.0.0.1", allow_edit)
    server.remote = remote_policy
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, doc, thread


def stop(server: PageServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(5)


@pytest.fixture
def running(tmp_path: Path) -> Iterator[tuple[PageServer, Path]]:
    server, doc, thread = start(tmp_path)
    yield server, doc
    stop(server, thread)


def post(server: PageServer, payload: dict[str, Any], *, cookie: bool = False) -> int:
    host = f"127.0.0.1:{server.port}"
    headers = {
        "Host": host,
        "Origin": f"http://{host}",
        "Content-Type": "application/json",
        "X-Varde-Token": server.token,
    }
    if cookie:
        headers["Cookie"] = f"{remote.cookie_name(server.port)}={server.access_key}"
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("POST", "/comments", json.dumps(payload), headers)
    status = conn.getresponse().status
    conn.close()
    return status


def answer(verdict: str, item: str = "ship", text: str = "") -> dict[str, Any]:
    return {
        "anchor": item,
        "kind": "decision",
        "item": item,
        "verdict": verdict,
        "text": text,
    }


@pytest.mark.parametrize(
    ("verdict", "text"), [("approved", ""), ("denied", ""), ("commented", "why not")]
)
def test_pages_decision_each_verdict_is_stored(running, verdict, text):
    server, doc = running
    assert post(server, answer(verdict, text=text)) == 201
    [row] = fold(read_rows(doc))
    assert (row["kind"], row["item"], row["verdict"], row["actor"]) == (
        "decision",
        "ship",
        verdict,
        "user",
    )
    if text:
        assert row["text"] == text


@pytest.mark.parametrize(
    "payload",
    [
        answer("commented", text="  "),
        answer("approved", item="ghost"),
        answer("maybe"),
        answer("denied", item="only"),
        {**answer("approved"), "item": 3},
    ],
)
def test_pages_decision_bad_answers_are_400(running, payload):
    server, doc = running
    assert post(server, payload) == 400
    assert read_rows(doc) == []


def test_pages_decision_escapes_block_text():
    body = (
        f'question = "{HOSTILE}"\ndiff = "{HOSTILE}"\n'
        f'[[evidence]]\nlabel = "{HOSTILE}"\ntext = "{HOSTILE}"\n'
    )
    out = render_page(ui_fence("decision", body, "d"), "t.md").body
    assert "<script" not in out
    assert out.count("&lt;script&gt;") == 4
    assert 'data-verdict="approved"' in out and 'data-verdict="commented"' in out


def test_pages_decision_invalid_block_renders_error_card():
    fence = '```ui id=d\nd = decision(options: ["approve"])\n```\n'
    out = render_page(fence, "t.md").body
    assert "vb-error" in out


def test_pages_decision_changes_only_the_log(running):
    server, doc = running
    before = {p.name: p.read_bytes() for p in doc.parent.iterdir()}
    assert post(server, answer("approved")) == 201
    after = {p.name: p.read_bytes() for p in doc.parent.iterdir()}
    assert set(after) - set(before) == {"plan.md.comments.jsonl"}
    assert {k: v for k, v in after.items() if k in before} == before


def test_pages_decision_remote_without_allow_edit_is_403(tmp_path):
    server, doc, thread = start(tmp_path, remote_policy=True)
    try:
        assert post(server, answer("approved"), cookie=True) == 403
        assert post(server, answer("approved")) == 403
        assert read_rows(doc) == []
    finally:
        stop(server, thread)


def test_pages_decision_remote_with_allow_edit_needs_cookie(tmp_path):
    server, doc, thread = start(tmp_path, remote_policy=True, allow_edit=True)
    try:
        assert post(server, answer("approved")) == 403
        assert post(server, answer("approved"), cookie=True) == 201
        assert len(read_rows(doc)) == 1
    finally:
        stop(server, thread)


def test_pages_decision_resolve_by_reply_folds_resolved(running):
    server, doc = running
    assert post(server, answer("approved")) == 201
    [row] = fold(read_rows(doc))
    assert row["state"] == "open"
    append_reply(doc, row["id"], "applied")
    [row] = fold(read_rows(doc))
    assert row["state"] == "resolved" and row["replies"][0]["text"] == "applied"


@pytest.mark.slow
def test_pages_decision_one_click(browser_session: Any, running) -> None:
    server, doc = running
    page = browser_session.new_page()
    page.set_default_timeout(10_000)
    posts: list[str] = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    page.goto(f"http://127.0.0.1:{server.port}/")
    page.wait_for_selector(".decision-verdict")
    page.locator('[data-item="ship"] [data-verdict="approved"]').click()
    page.wait_for_function(
        "() => document.querySelector('[data-item=ship][data-verdict]')"
    )
    assert len(posts) == 1
    page.locator('[data-item="ship"] [data-verdict="commented"]').click()
    assert page.locator('[data-item="ship"] .decision-text').is_visible()
    assert len(posts) == 1
    page.fill('[data-item="ship"] .decision-text', "needs a test")
    page.locator('[data-item="ship"] .decision-send').click()
    page.wait_for_function(
        "() => document.querySelector('[data-item=ship]').dataset.verdict"
        " === 'commented'"
    )
    assert len(posts) == 2
    verdicts = [r["value"] for r in fold(read_rows(doc))]  # unified answer row
    assert verdicts == ["approved", "commented"]
    page.goto("about:blank")


def test_pages_decision_buttons_disabled_while_posting() -> None:
    js = (Path(remote.__file__).parent / "static" / "recap.js").read_text()
    start = js.index("async function decide")
    body = js[start : js.index("function chooseDecision")]
    off, post, on = (
        body.index(s) for s in ("disabled = true", "await post(", "disabled = false")
    )
    assert off < post < on
