"""Suggestions and direct block edit over the page server."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from varde_learn.docs.pages.comments import (
    append_comment,
    comments_path,
    fold,
    read_rows,
)
from varde_learn.docs.pages.render import render_page
from varde_learn.docs.pages.serve import PageServer

DOC = (
    "---\nstatus: todo\n---\n\n# Title\n\nHello **world**.\n\n"
    "- one\n- two\n\n```deps\nroot:\na: root\n```\n\n## Part\n\nSecond.\n"
)


class Client:
    def __init__(self, server: PageServer, doc: Path) -> None:
        self.server, self.doc = server, doc
        self.host = f"127.0.0.1:{server.port}"

    def call(
        self,
        method: str,
        path: str,
        payload: object = None,
        raw: bytes | None = None,
        **overrides: str | None,
    ) -> tuple[int, bytes]:
        body = raw if raw is not None else json.dumps(payload).encode()
        headers: dict[str, str | None] = {
            "Host": self.host,
            "Content-Type": "application/json",
            "Origin": f"http://{self.host}",
            "X-Varde-Token": self.server.token,
        }
        headers.update(overrides)
        sent = {k: v for k, v in headers.items() if v is not None}
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        conn.request(
            method, path, body=body if method == "POST" else None, headers=sent
        )
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    def post(self, path: str, payload: object, **overrides: str | None):
        # header overrides are strings; none of them is the `raw` body argument
        return self.call("POST", path, payload, **overrides)  # type: ignore[arg-type]

    def block(self, anchor: str) -> dict[str, str]:
        status, data = self.call("GET", f"/block?anchor={anchor}")
        assert status == 200, data
        return json.loads(data)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[Client]:
    doc = tmp_path / "plan.md"
    doc.write_bytes(DOC.encode())
    server = PageServer(doc, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield Client(server, doc)
    server.shutdown()
    server.server_close()
    thread.join(5)


class Anchors:
    """Find a block's anchor by the start of its visible text."""

    def __init__(self, doc: Path) -> None:
        page = render_page(doc.read_text(encoding="utf-8"), doc.name)
        self.blocks = page.blocks

    def __getitem__(self, prefix: str) -> str:
        return next(b.anchor for b in self.blocks if b.text.startswith(prefix))


def anchors(doc: Path) -> Anchors:
    return Anchors(doc)


def test_edit_changes_only_the_target_block_bytes(client: Client) -> None:
    anchor = anchors(client.doc)["Hello"]
    block = client.block(anchor)
    assert block["source"] == "Hello **world**."
    status, _ = client.post(
        "/edit", {"anchor": anchor, "base_hash": block["hash"], "new_source": "Bye."}
    )
    assert status == 200
    assert client.doc.read_bytes() == DOC.replace("Hello **world**.", "Bye.").encode()


def test_edit_a_multiline_block(client: Client) -> None:
    ids = anchors(client.doc)
    listing = client.block(ids["one"])
    assert listing["source"] == "- one\n- two"
    new = "- one\n- two\n- three"
    status, _ = client.post(
        "/edit",
        {"anchor": ids["one"], "base_hash": listing["hash"], "new_source": new},
    )
    assert status == 200
    assert client.doc.read_text().replace(new, "- one\n- two") == DOC


def test_edit_preserves_crlf_line_endings(client: Client) -> None:
    client.doc.write_bytes(DOC.replace("\n", "\r\n").encode())
    anchor = anchors(client.doc)["Hello"]
    block = client.block(anchor)
    status, _ = client.post(
        "/edit",
        {"anchor": anchor, "base_hash": block["hash"], "new_source": "A\nB"},
    )
    assert status == 200
    expected = DOC.replace("Hello **world**.", "A\nB").replace("\n", "\r\n")
    assert client.doc.read_bytes() == expected.encode()


def test_stale_hash_is_409_and_file_untouched(client: Client) -> None:
    anchor = anchors(client.doc)["Hello"]
    status, _ = client.post(
        "/edit", {"anchor": anchor, "base_hash": "000000000000", "new_source": "x"}
    )
    assert status == 409
    assert client.doc.read_bytes() == DOC.encode()


def test_unknown_anchor_is_404(client: Client) -> None:
    status, _ = client.post(
        "/edit", {"anchor": "nope", "base_hash": "0", "new_source": "x"}
    )
    assert status == 404


def test_edit_rejects_missing_token_and_wrong_origin(client: Client) -> None:
    anchor = anchors(client.doc)["Hello"]
    payload = {"anchor": anchor, "base_hash": "x", "new_source": "y"}
    assert client.post("/edit", payload, **{"X-Varde-Token": None})[0] == 403
    assert client.post("/edit", payload, **{"X-Varde-Token": "wrong"})[0] == 403
    assert client.post("/edit", payload, Origin="http://evil.test")[0] == 403
    assert client.post("/edit", payload, Origin=None)[0] == 403
    assert client.post("/edit", payload, **{"Content-Type": "text/plain"})[0] == 415
    assert client.doc.read_bytes() == DOC.encode()


def test_edit_oversize_is_413(client: Client) -> None:
    anchor = anchors(client.doc)["Hello"]
    block = client.block(anchor)
    huge = {"anchor": anchor, "base_hash": block["hash"], "new_source": "x" * 70_000}
    assert client.post("/edit", huge)[0] == 413
    big = {"anchor": anchor, "base_hash": block["hash"], "new_source": "x" * 40_000}
    assert client.post("/edit", big)[0] == 413
    assert client.doc.read_bytes() == DOC.encode()


def test_bad_edit_body_is_400(client: Client) -> None:
    assert client.post("/edit", {"anchor": "title"})[0] == 400
    assert client.call("POST", "/edit", raw=b"not json")[0] == 400


def test_concurrent_edits_do_not_corrupt_the_file(client: Client) -> None:
    ids = anchors(client.doc)
    hello = client.block(ids["Hello"])
    second = client.block(ids["Second"])
    results: list[int] = []

    def edit(anchor: str, block: dict[str, str], text: str) -> None:
        payload = {"anchor": anchor, "base_hash": block["hash"], "new_source": text}
        results.append(client.post("/edit", payload)[0])

    threads = [
        threading.Thread(target=edit, args=(ids["Hello"], hello, "First!")),
        threading.Thread(target=edit, args=(ids["Second"], second, "Last!")),
        threading.Thread(target=edit, args=(ids["Hello"], hello, "Rival!")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert sorted(results) in ([200, 200, 409], [200, 200, 200])
    text = client.doc.read_text()
    assert text.count("Last!") == 1
    assert ("First!" in text) != ("Rival!" in text) or sorted(results) == [200] * 3
    assert "# Title" in text and "```deps" in text and "## Part" in text


def test_suggestion_folds_with_kind_and_renders_redline(client: Client) -> None:
    anchor = anchors(client.doc)["Hello"]
    status, data = client.post(
        "/comments",
        {"anchor": anchor, "kind": "suggestion", "quote": "Hello", "replacement": "Hi"},
    )
    assert status == 201
    folded = fold(read_rows(client.doc))
    assert folded[0]["kind"] == "suggestion"
    assert (folded[0]["quote"], folded[0]["replacement"]) == ("Hello", "Hi")
    _, page = client.call("GET", "/")
    assert b"<del>Hello</del> <ins>Hi</ins>" in page
    assert json.loads(data)["id"] == folded[0]["id"]


def test_suggestion_needs_a_quote_and_kind_is_checked(client: Client) -> None:
    anchor = anchors(client.doc)["Hello"]
    assert (
        client.post("/comments", {"anchor": anchor, "text": "t", "kind": "drift"})[0]
        == 400
    )
    sugg = {"anchor": anchor, "kind": "suggestion", "replacement": "x"}
    assert client.post("/comments", sugg)[0] == 400
    long = {**sugg, "quote": "q" * 201}
    assert client.post("/comments", long)[0] == 400


def test_unknown_kind_and_old_rows_fold_as_comment(tmp_path: Path) -> None:
    doc = tmp_path / "plan.md"
    doc.write_text(DOC)
    rows = [
        {"id": "c1", "ts": "t", "anchor": "title", "text": "old", "state": "open"},
        {"id": "c2", "ts": "t", "anchor": "title", "text": "new", "state": "open",
         "kind": "mystery"},
    ]  # fmt: skip
    comments_path(doc).write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert [c["kind"] for c in fold(read_rows(doc))] == ["comment", "comment"]
    row = append_comment(doc, "title", "", "d", extra={"kind": "drift", "item": "t1"})
    kinds = {c["id"]: c["kind"] for c in fold(read_rows(doc))}
    assert kinds[row["id"]] == "drift"


def test_accept_applies_edit_and_records_actor(client: Client) -> None:
    anchor = anchors(client.doc)["Hello"]
    _, data = client.post(
        "/comments",
        {
            "anchor": anchor,
            "kind": "suggestion",
            "quote": "**world**",
            "replacement": "all",
        },
    )
    cid = json.loads(data)["id"]
    block = client.block(anchor)
    status, _ = client.post("/accept", {"comment_id": cid, "base_hash": block["hash"]})
    assert status == 200
    assert client.doc.read_bytes() == DOC.replace("**world**", "all").encode()
    applied = fold(read_rows(client.doc))[0]
    assert applied["state"] == "resolved"
    assert applied["applied_by"] == "user"
    again, _ = client.post("/accept", {"comment_id": cid, "base_hash": block["hash"]})
    assert again == 409


def test_accept_rejects_stale_hash_and_missing_quote(client: Client) -> None:
    anchor = anchors(client.doc)["Hello"]
    _, data = client.post(
        "/comments",
        {"anchor": anchor, "kind": "suggestion", "quote": "gone", "replacement": "x"},
    )
    cid = json.loads(data)["id"]
    block = client.block(anchor)
    assert client.post("/accept", {"comment_id": cid, "base_hash": "0"})[0] == 409
    assert (
        client.post("/accept", {"comment_id": cid, "base_hash": block["hash"]})[0]
        == 409
    )
    assert client.post("/accept", {"comment_id": "nope", "base_hash": "0"})[0] == 404
    assert (
        client.post(
            "/accept", {"comment_id": cid, "base_hash": "0"}, Origin="http://x"
        )[0]
        == 403
    )
    assert (
        client.post("/accept", {"comment_id": cid}, **{"X-Varde-Token": None})[0] == 403
    )
    assert client.doc.read_bytes() == DOC.encode()


def test_edit_keeps_a_symlinked_document_a_symlink(tmp_path: Path) -> None:
    target = tmp_path / "real.md"
    target.write_bytes(DOC.encode())
    link = tmp_path / "link.md"
    link.symlink_to(target)
    server = PageServer(link, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        c = Client(server, link)
        anchor = anchors(link)["Hello"]
        block = c.block(anchor)
        status, _ = c.post(
            "/edit",
            {"anchor": anchor, "base_hash": block["hash"], "new_source": "Bye."},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
    assert status == 200
    assert link.is_symlink()
    assert target.read_bytes() == DOC.replace("Hello **world**.", "Bye.").encode()


@pytest.mark.parametrize("sep", ["\x0c", "\x85", " "])
def test_edit_keeps_unusual_line_separators(client: Client, sep: str) -> None:
    text = f"# T\n\nfirst para{sep}## H2\n\nlast\n"
    client.doc.write_bytes(text.encode())
    anchor = anchors(client.doc)["first"]
    block = client.block(anchor)
    status, _ = client.post(
        "/edit",
        {"anchor": anchor, "base_hash": block["hash"], "new_source": "changed"},
    )
    assert status == 200
    assert client.doc.read_text(encoding="utf-8") == (
        f"# T\n\nchanged{sep}## H2\n\nlast\n"
    )


def test_accept_marks_applied_under_the_lock_and_reports_failure(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    anchor = anchors(client.doc)["Hello"]
    _, data = client.post(
        "/comments",
        {
            "anchor": anchor,
            "kind": "suggestion",
            "quote": "**world**",
            "replacement": "x",
        },
    )
    cid = json.loads(data)["id"]
    held: list[bool] = []

    def failing(*_args: object) -> None:
        held.append(client.server.edit_lock.locked())
        raise OSError("disk full")

    monkeypatch.setattr("varde_learn.docs.pages.serve.mark_applied", failing)
    block = client.block(anchor)
    status, body = client.post(
        "/accept", {"comment_id": cid, "base_hash": block["hash"]}
    )
    assert status == 500
    assert b"follow-up failed" in body
    assert held == [True]
    assert not client.server.edit_lock.locked()
