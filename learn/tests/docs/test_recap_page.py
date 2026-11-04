"""The `recap` block: escaping, anchors, drift buttons, and the drift comment route."""

from __future__ import annotations

import http.client
import json
import re
import threading
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path

import pytest
from varde_learn.docs.pages.blocks.statement import statement_text
from varde_learn.docs.pages.comments import fold, read_rows
from varde_learn.docs.pages.render import render_page
from varde_learn.docs.pages.serve import PageServer

HOSTILE = '<script>alert(1)</script>"><img src=x onerror=alert(1)>'
UNSAFE = [r"<script", r"style=", r"<[^>]*\son[a-z]+=", r"<img"]


def recap_data() -> dict:
    return {
        "base": "main",
        "head": "HEAD",
        "plan": "demo",
        "rows": [
            {
                "file": f"src/{HOSTILE}.py",
                "old_file": None,
                "status": "M",
                "binary": False,
                "tasks": ["t1-api"],
                "shared": False,
                "blocks": ["api"],
                "added": [[3, 5]],
                "removed": [[3, 4]],
                "hunk": f"@@ -3,2 +3,3 @@\n-{HOSTILE}\n+{HOSTILE}",
                "truncated": False,
                "drift": [],
            },
            {
                "file": "stray.txt",
                "old_file": None,
                "status": "A",
                "binary": False,
                "tasks": [],
                "shared": False,
                "blocks": [],
                "added": [[1, 1]],
                "removed": [],
                "hunk": "@@ -0,0 +1 @@\n+x",
                "truncated": False,
                "drift": ["unplanned"],
            },
        ],
        "untouched": [{"task": "t2-model", "owns": "src/model.py"}],
        "unverified": ["model"],
        "summary": {"files": 2, "unplanned": 1, "untouched": 1, "unverified": 1},
    }


def recap_fence(data: dict) -> str:
    return f"```ui id=rc\n{statement_text('rc', 'recap', data)}\n```\n"


def render(data: dict) -> str:
    return render_page(recap_fence(data), "plan.md").body


def test_hostile_text_is_escaped_and_nothing_unsafe_is_emitted():
    out = render(recap_data())
    for pattern in UNSAFE:
        assert not re.search(pattern, out), pattern
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out


def test_mapping_drift_and_anchors_present():
    out = render(recap_data())
    assert 'id="recap-rc-f0"' in out and 'href="#recap-rc-f0"' in out
    assert 'id="recap-rc-f0-a3-5"' in out and 'id="recap-rc-f0-r3-4"' in out
    assert "<td>api</td>" in out
    assert "no changed file" in out
    for key in (
        "unplanned:stray.txt",
        "untouched:t2-model:src/model.py",
        "unverified:model",
    ):
        assert f'data-item="{key}"' in out
    assert out.count('data-verdict="accepted"') == 3
    assert "http://" not in out and "https://" not in out


@pytest.mark.parametrize("bad", [{"rows": 3}, {"rows": [{"file": "a"}]}, {}])
def test_invalid_props_render_error_card(bad):
    out = render(bad)
    assert "vb-error" in out and "recap block has" in out
    assert 'class="recap' not in out


def test_hostile_item_attribute_cannot_break_out():
    data = recap_data()
    data["unverified"] = ['x" onmouseover="alert(1)']
    out = render(data)
    names: list[str] = []

    class Collect(HTMLParser):
        def handle_starttag(self, tag, attrs):
            names.extend(name for name, _ in attrs)

    Collect().feed(out)
    assert not [n for n in names if n.startswith("on")]


class Running:
    def __init__(self, server: PageServer, doc: Path) -> None:
        self.server, self.doc = server, doc

    def post(self, payload: dict, **overrides: str | None) -> int:
        host = f"127.0.0.1:{self.server.port}"
        headers: dict[str, str | None] = {
            "Host": host,
            "Content-Type": "application/json",
            "Origin": f"http://{host}",
            "X-Varde-Token": self.server.token,
            **overrides,
        }
        sent = {k: v for k, v in headers.items() if v is not None}
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        conn.request("POST", "/comments", json.dumps(payload).encode(), sent)
        status = conn.getresponse().status
        conn.close()
        return status


@pytest.fixture
def running(tmp_path: Path) -> Iterator[Running]:
    doc = tmp_path / "plan.md"
    doc.write_text("# Plan\n\n" + recap_fence(recap_data()))
    server = PageServer(doc, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield Running(server, doc)
    server.shutdown()
    server.server_close()
    thread.join(5)


def drift(verdict: str = "accepted", item: str = "unverified:model") -> dict:
    return {
        "anchor": "rc",
        "kind": "drift",
        "item": item,
        "verdict": verdict,
        "text": "",
    }


def test_drift_row_is_stored_with_item_and_verdict(running):
    assert running.post(drift("rejected")) == 201
    [row] = fold(read_rows(running.doc))
    assert (row["kind"], row["item"], row["verdict"]) == (
        "drift",
        "unverified:model",
        "rejected",
    )
    assert row["anchor"] == "rc"


@pytest.mark.parametrize(
    "payload",
    [
        drift("maybe"),
        drift(item=""),
        {**drift(), "item": 3},
        {**drift(), "verdict": None},
    ],
)
def test_bad_drift_fields_are_400(running, payload):
    assert running.post(payload) == 400
    assert read_rows(running.doc) == []


def test_drift_needs_token_and_origin(running):
    assert running.post(drift(), **{"X-Varde-Token": "wrong"}) == 403
    assert running.post(drift(), Origin="http://evil.example") == 403
    assert read_rows(running.doc) == []


def test_page_serves_recap_script_without_inline_script(running):
    host = f"127.0.0.1:{running.server.port}"
    conn = http.client.HTTPConnection("127.0.0.1", running.server.port, timeout=5)
    conn.request("GET", "/static/recap.js", headers={"Host": host})
    response = conn.getresponse()
    source = response.read().decode()
    content_type = response.getheader("Content-Type") or ""
    assert response.status == 200 and "javascript" in content_type
    for banned in ("eval(", "innerHTML", "insertAdjacentHTML", "document.write"):
        assert banned not in source
    conn.close()
