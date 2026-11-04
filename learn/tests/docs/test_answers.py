"""`validate_answer` and the `answer` row; each rejection writes nothing."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from varde_learn.docs.pages.answers import answer_value, validate_answer
from varde_learn.docs.pages.comments import comments_path, fold, read_rows
from varde_learn.docs.pages.serve import PageServer
from varde_learn.docs.pages.store import DecisionDenied, store_comment

DOC = (
    "# Plan\n\nBody.\n\n"
    "```ui\n"
    'ship = decision(question: "Ship?", options: ["approve", "deny", "comment"])\n'
    'only = decision(question: "Only?", options: ["approve"])\n'
    'go = decision(question: "Go?", options: ["approve", "deny"])\n'
    'bad = decision(question: "Bad?", options: ["maybe"])\n'
    'view = table(columns: ["a"], rows: [["1"]])\n'
    "```\n"
)


def row(item: str, value: object, text: str = "", kind: str = "answer") -> bytes:
    data = {"anchor": item, "kind": kind, "item": item, "value": value, "text": text}
    return json.dumps(data).encode()


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    path = tmp_path / "plan.md"
    path.write_text(DOC, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("item", "value", "text"),
    [
        ("ship", "approved", ""),
        ("ship", "denied", ""),
        ("ship", "commented", "why"),
        ("only", "approved", ""),
        ("go", "approved", ""),
        ("go", "denied", "because"),
    ],
)
def test_validate_answer_accepts_what_the_component_offers(item, value, text):
    validate_answer(DOC, item, value, text)


@pytest.mark.parametrize(
    ("item", "value", "text", "message"),
    [
        ("ghost", "approved", "", "unknown answer block"),
        ("", "approved", "", "item needs"),
        ("x" * 601, "approved", "", "item needs"),
        ("view", "approved", "", "unknown answer block"),  # no answer schema
        ("bad", "approved", "", "unknown answer block"),  # invalid props
        ("ship", "maybe", "", "value must be"),
        ("only", "denied", "", "value must be"),
        ("go", "commented", "x", "value must be"),
        ("ship", ["approved"], "", "value must be"),
        ("ship", {"a": 1}, "", "value must be"),
        ("ship", 1, "", "value must be"),
        ("ship", None, "", "value must be"),
        ("ship", True, "", "value must be"),
        ("ship", "commented", "   ", "needs text"),
        ("ship", "approved", "t" * 8001, "longer than"),
    ],
)
def test_validate_answer_rejects(item, value, text, message):
    with pytest.raises(ValueError, match=message):
        validate_answer(DOC, item, value, text)


def test_answer_value_reads_old_decision_rows_as_answers() -> None:
    assert answer_value({"kind": "decision", "verdict": "denied"}) == "denied"
    assert answer_value({"kind": "answer", "value": "approved"}) == "approved"
    assert answer_value({"kind": "answer"}) is None


def test_store_answer_row_shape(doc: Path) -> None:
    stored = store_comment(doc, row("ship", "approved"), decisions_open=True)
    [found] = fold(read_rows(doc))
    assert found["id"] == stored["id"]
    assert (found["kind"], found["item"], found["value"], found["actor"]) == (
        "answer",
        "ship",
        "approved",
        "user",
    )
    assert "verdict" not in found and found["anchor"] == "ship"


def test_store_old_decision_row_is_still_accepted(doc: Path) -> None:
    raw = json.dumps(
        {"anchor": "ship", "kind": "decision", "item": "ship", "verdict": "denied"}
    ).encode()
    store_comment(doc, raw, decisions_open=True)
    [found] = fold(read_rows(doc))
    assert (found["kind"], answer_value(found)) == ("decision", "denied")


def test_store_answer_needs_decisions_open_and_writes_nothing(doc: Path) -> None:
    with pytest.raises(DecisionDenied):
        store_comment(doc, row("ship", "approved"), decisions_open=False)
    assert not comments_path(doc).exists()


@pytest.mark.parametrize(
    "raw",
    [
        row("ghost", "approved"),
        row("ship", "maybe"),
        row("ship", "commented", " "),
        row("only", "denied"),
        json.dumps({"anchor": "ship", "kind": "answer", "item": "ship"}).encode(),
        json.dumps(
            {"anchor": "ship", "kind": "answer", "item": 3, "value": "x"}
        ).encode(),
        json.dumps({"anchor": "ship", "kind": "answer", "value": "approved"}).encode(),
        json.dumps(
            {
                "anchor": "ship",
                "kind": "answer",
                "item": "ship",
                "value": "approved",
                "text": 5,
            }
        ).encode(),
        row("ship", "approved", "t" * 8001),
        row("../ship", "approved"),
    ],
)
def test_store_rejects_and_writes_nothing(doc: Path, raw: bytes) -> None:
    with pytest.raises(ValueError):
        store_comment(doc, raw, decisions_open=True)
    assert not comments_path(doc).exists()


def test_answer_rows_are_never_routed_to_a_source(doc: Path, tmp_path: Path) -> None:
    raw = json.dumps(
        {
            "anchor": "ship",
            "kind": "answer",
            "item": "ship",
            "value": "approved",
            "part": "p",
        }
    ).encode()
    with pytest.raises(ValueError, match="only a comment"):
        store_comment(doc, raw, decisions_open=True)
    assert not comments_path(doc).exists()


# --- over HTTP ---------------------------------------------------------------------


@pytest.fixture
def server(doc: Path) -> Iterator[PageServer]:
    page_server = PageServer(doc, 0, "127.0.0.1", True)
    thread = threading.Thread(target=page_server.serve_forever, daemon=True)
    thread.start()
    yield page_server
    page_server.shutdown()
    page_server.server_close()
    thread.join(5)


def http_post(server: PageServer, raw: bytes) -> int:
    host = f"127.0.0.1:{server.port}"
    headers = {
        "Host": host,
        "Origin": f"http://{host}",
        "Content-Type": "application/json",
        "X-Varde-Token": server.token,
    }
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("POST", "/comments", raw, headers)
    status = conn.getresponse().status
    conn.close()
    return status


def test_served_valid_answer_is_201_and_delivered_by_watch(server: PageServer) -> None:
    from varde_learn.docs.pages.watch import new_open_comments

    assert http_post(server, row("go", "denied", "too risky")) == 201
    [fresh] = new_open_comments(server.doc, set())
    assert (fresh["kind"], fresh["item"], fresh["value"]) == ("answer", "go", "denied")


@pytest.mark.parametrize(
    "raw",
    [
        row("ghost", "approved"),
        row("go", "commented"),
        row("view", "x"),
        row("ship", ["approved"]),
        row("ship", "approved", "t" * 9000),
        b'{"kind": "answer"}',
    ],
)
def test_served_invalid_answer_is_400_and_writes_nothing(
    server: PageServer, raw: bytes
) -> None:
    assert http_post(server, raw) == 400
    assert not comments_path(server.doc).exists()


def test_served_answer_with_edit_off_is_403_and_writes_nothing(
    doc: Path, tmp_path: Path
) -> None:
    closed = PageServer(doc, 0, "127.0.0.1", False)
    closed.remote = True
    thread = threading.Thread(target=closed.serve_forever, daemon=True)
    thread.start()
    try:
        assert http_post(closed, row("ship", "approved")) == 403
    finally:
        closed.shutdown()
        closed.server_close()
        thread.join(5)
    assert not comments_path(doc).exists()


def test_comment_line_for_answer_rows() -> None:
    from varde_learn.docs.pages.watch import comment_line

    line = comment_line(
        {"id": "c1", "kind": "answer", "item": "go", "value": "denied", "text": "no"}
    )
    assert line == "answer c1 go denied no"
    old = comment_line(
        {"id": "c2", "kind": "decision", "item": "go", "verdict": "denied", "text": "x"}
    )
    assert old == "decision c2 go denied x"


# --- review fixes -----------------------------------------------------------------

BIDI = chr(0x202E)  # right-to-left override


@pytest.mark.parametrize("bad", ["\x00", "\x1b]0;x\x07", "\x85", BIDI, "\x7f"])
def test_validate_answer_rejects_control_characters_in_text(bad: str) -> None:
    with pytest.raises(ValueError, match="control characters"):
        validate_answer(DOC, "go", "approved", f"a{bad}b")


def test_validate_answer_allows_newlines_and_tabs_in_text() -> None:
    validate_answer(DOC, "go", "approved", "line one\n\tline two\r\n")


def test_validate_answer_rejects_control_characters_in_string_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from varde_learn.docs.pages import answers
    from varde_learn.docs.pages.blocks.spec import AnswerSchema

    schema = AnswerSchema("string", ("text",), ())
    monkeypatch.setattr(answers, "answer_schema", lambda doc, item: schema)
    validate_answer(DOC, "x", "plain", "")
    for bad in ("a\x00b", "a\x1bb", f"a{BIDI}b"):
        with pytest.raises(ValueError, match="control characters"):
            validate_answer(DOC, "x", bad, "")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), True])
def test_number_answers_must_be_finite(
    monkeypatch: pytest.MonkeyPatch, bad: object
) -> None:
    from varde_learn.docs.pages import answers
    from varde_learn.docs.pages.blocks.spec import AnswerSchema

    schema = AnswerSchema("number", (), ())
    monkeypatch.setattr(answers, "answer_schema", lambda doc, item: schema)
    validate_answer(DOC, "x", 3.5, "")
    with pytest.raises(ValueError, match="value must be"):
        validate_answer(DOC, "x", bad, "")


def test_comment_line_replaces_terminal_controls() -> None:
    from varde_learn.docs.pages.watch import comment_line

    hostile = f"\x1b]0;pwn\x07 hi\x00 {BIDI} end"
    line = comment_line(
        {"id": "c1", "kind": "answer", "item": "go", "value": "x", "text": hostile}
    )
    assert line == "answer c1 go x ]0;pwn hi end"
    assert not any(ch in line for ch in ("\x1b", "\x07", "\x00", BIDI))


def test_cli_comment_text_uses_the_same_cleaning() -> None:
    from varde_learn.docs.pages.cli import comment_text

    out = comment_text(
        {
            "id": "c1",
            "kind": "comment",
            "state": "open",
            "anchor": "a",
            "text": "x\x1b[31m y",
            "replies": [{"actor": "a\x00", "text": f"{BIDI}q"}],
        }
    )
    assert "\x1b" not in out and "\x00" not in out and BIDI not in out


def test_duplicate_block_id_cannot_widen_allowed() -> None:
    ui = (
        "```ui\n"
        'go = decision(question: "Go?", options: ["approve"])\n'
        "```\n\n```ui\n"
        'go = decision(question: "Go?", options: ["approve", "deny"])\n'
        "```\n"
    )
    validate_answer(ui, "go", "approved", "")
    with pytest.raises(ValueError, match="value must be"):
        validate_answer(ui, "go", "denied", "")
