"""Server rule: `store_comment` refuses row kinds a block type cannot take."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from varde_learn.docs.pages.actions import BLOCK_TYPES, kind_allowed
from varde_learn.docs.pages.comments import comments_path, fold, read_rows
from varde_learn.docs.pages.render import render_page
from varde_learn.docs.pages.store import DecisionDenied, store_comment

DOC = """# Title

Some prose.

- one
- two

| a | b |
| - | - |
| 1 | 2 |

```py
x = 1
```

```ui
pick = choice(question: "Which?", options: ["a", "b"])
ship = decision(question: "Ship?", options: ["approve"])
note = callout(body: "hi")
rc = recap(t: "x")
oops = nonesuch()
inc = include(source: "missing.md", select: "heading:x")
```
"""
KINDS = ("comment", "suggestion", "answer", "decision", "drift")
# one anchor per block type, found by rendering the document
ANCHORS = {
    "heading": "title",
    "prose": "title/1",
    "list": "title/2",
    "table": "title/3",
    "code": "title/4",
    "widget": "pick",
    "decision": "ship",
    "visual": "note",
    "status": "rc",
    "error": "oops",
    "part": "inc",
}


def body(anchor: str, kind: str) -> bytes:
    data: dict[str, object] = {"anchor": anchor, "text": "note", "kind": kind}
    if kind == "suggestion":
        data.update(replacement="new", quote="q")
    if kind in ("answer", "decision"):
        data.update(text="", item=anchor, value="a" if anchor == "pick" else "approved")
        if kind == "decision":
            data["verdict"] = data.pop("value")
    if kind == "drift":
        data.update(item="goal", verdict="accepted")
    return json.dumps(data).encode()


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    path = tmp_path / "plan.md"
    path.write_text(DOC, encoding="utf-8")
    return path


def sidecar(doc: Path) -> str:
    path = comments_path(doc)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_anchor_table_matches_the_rendered_types(doc: Path) -> None:
    blocks = render_page(DOC, doc.name).blocks
    found = {b.anchor: b.block_type for b in blocks}
    assert {t: found.get(a) for t, a in ANCHORS.items()} == {t: t for t in ANCHORS}
    assert set(ANCHORS) == set(BLOCK_TYPES)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("block_type", BLOCK_TYPES)
def test_every_type_and_kind_cell(doc: Path, block_type: str, kind: str) -> None:
    row_kind = "answer" if kind == "decision" else kind
    allowed = kind_allowed(block_type, row_kind)
    raw = body(ANCHORS[block_type], kind)
    if allowed:
        row = store_comment(doc, raw, decisions_open=True)
        assert row["anchor"] == ANCHORS[block_type]
        assert len(read_rows(doc)) == 1
        return
    with pytest.raises(ValueError, match=f"{kind} is not allowed on {block_type}"):
        store_comment(doc, raw, decisions_open=True)
    assert sidecar(doc) == ""


@pytest.mark.parametrize("kind", ["suggestion", "answer", "decision", "drift"])
def test_unresolved_anchor_takes_only_a_comment(doc: Path, kind: str) -> None:
    with pytest.raises(ValueError, match="no longer exists"):
        store_comment(doc, body("gone/1", kind), decisions_open=True)
    assert sidecar(doc) == ""
    assert store_comment(doc, body("gone/1", "comment"), decisions_open=True)["id"]


def test_forged_suggestion_on_code_is_refused(doc: Path) -> None:
    raw = json.dumps(
        {
            "anchor": "title/4",
            "kind": "suggestion",
            "replacement": "evil",
            "text": "x",
            "quote": "x = 1",
        }
    ).encode()
    with pytest.raises(ValueError, match="suggestion is not allowed on code"):
        store_comment(doc, raw, decisions_open=False)
    assert sidecar(doc) == ""


def test_closed_decisions_still_deny_before_the_kind_check(doc: Path) -> None:
    with pytest.raises(DecisionDenied):
        store_comment(doc, body("title/1", "answer"), decisions_open=False)


def test_old_suggestion_row_on_a_code_block_still_reads(doc: Path) -> None:
    old = {
        "id": "c1",
        "ts": "2026-01-01T00:00:00Z",
        "anchor": "title/4",
        "quote": "x = 1",
        "text": "old",
        "state": "open",
        "actor": "user",
        "kind": "suggestion",
        "replacement": "y = 2",
    }
    comments_path(doc).write_text(json.dumps(old) + "\n", encoding="utf-8")
    [thread] = fold(read_rows(doc))
    assert (thread["id"], thread["kind"], thread["state"]) == (
        "c1",
        "suggestion",
        "open",
    )
