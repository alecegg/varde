"""Comments on included parts through the daemon: routing and refusals."""

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import Served

Factory = Callable[..., Served]
EDIT = "[serve]\nallow_edit = true\n"
SOURCE = "# Src\n\nIntro.\n\n## Beta\n\nLast.\n\n## Other\n\nElse.\n"
INCLUDE = 'b = include(source: "src.md", select: "heading:beta")'
PAGE = f"```ui\n{INCLUDE}\n```\n\n## Own\n\nText.\n"
COMMENTS = "/api/docs/notes/page.md/comments"


@pytest.fixture
def served(served_factory: Factory) -> Served:
    made = served_factory(EDIT)
    (made.working / "notes").mkdir()
    (made.working / "notes" / "src.md").write_text(SOURCE, encoding="utf-8")
    (made.working / "notes" / "page.md").write_text(PAGE, encoding="utf-8")
    return made


def sidecar(served: Served, name: str) -> Path:
    return served.working / "notes" / f"{name}.comments.jsonl"


def untouched(served: Served) -> bool:
    return not any(served.working.rglob("*.comments.jsonl"))


def test_part_comment_goes_to_the_source_sidecar(served: Served) -> None:
    status, body = served.request(
        "POST", COMMENTS, {"anchor": "beta/1", "text": "hi", "part": "b"}, scope="mcp"
    )
    assert status == 201, body
    assert body["id"] in sidecar(served, "src.md").read_text()  # type: ignore[index]
    assert not sidecar(served, "page.md").exists()
    _, doc = served.request("GET", "/api/docs/notes/page.md")
    [comment] = doc["comments"]  # type: ignore[index]
    assert (comment["id"], comment["part"]) == (body["id"], "b")  # type: ignore[index]


def test_page_owned_comment_goes_to_the_page_sidecar(served: Served) -> None:
    status, _ = served.request("POST", COMMENTS, {"anchor": "own/1", "text": "x"})
    assert status == 201
    assert not sidecar(served, "src.md").exists()
    assert sidecar(served, "page.md").exists()


@pytest.mark.parametrize("kind", ["suggestion", "drift", "decision", "answer"])
def test_kind_with_part_is_400_and_writes_nothing(served: Served, kind: str) -> None:
    body = {
        "anchor": "beta/1",
        "text": "x",
        "part": "b",
        "kind": kind,
        "quote": "Last.",
    }
    assert served.request("POST", COMMENTS, body)[0] == 400
    assert untouched(served)


@pytest.mark.parametrize(
    "part", ["ghost", "src.md", "../src.md", "/etc/passwd", "", 7, ["b"]]
)
def test_allowlist_unknown_part_is_400(served: Served, part: object) -> None:
    body = {"anchor": "beta/1", "text": "x", "part": part}
    assert served.request("POST", COMMENTS, body)[0] == 400
    assert untouched(served)


def test_allowlist_anchor_outside_the_region_is_400(served: Served) -> None:
    for anchor in ("other/1", "src", "ghost"):
        body = {"anchor": anchor, "text": "x", "part": "b"}
        assert served.request("POST", COMMENTS, body)[0] == 400
    assert untouched(served)


def test_traversal_include_source_is_400(served: Served) -> None:
    (served.working / "secret.md").write_text(SOURCE, encoding="utf-8")
    page = served.working / "notes" / "page.md"
    page.write_text(PAGE.replace("src.md", "../secret.md"), encoding="utf-8")
    body = {"anchor": "beta/1", "text": "x", "part": "b"}
    assert served.request("POST", COMMENTS, body)[0] == 400
    assert untouched(served)


def test_symlink_source_outside_the_roots_is_400(
    served: Served, tmp_path: Path
) -> None:
    outside = tmp_path / "away"
    outside.mkdir()
    (outside / "x.md").write_text(SOURCE, encoding="utf-8")
    link = served.working / "notes" / "src.md"
    link.unlink()
    link.symlink_to(outside / "x.md")
    body = {"anchor": "beta/1", "text": "x", "part": "b"}
    assert served.request("POST", COMMENTS, body)[0] == 400
    assert list(outside.iterdir()) == [outside / "x.md"]
    assert untouched(served)


def test_symlinked_sidecar_is_400_and_its_target_untouched(
    served: Served, tmp_path: Path
) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("keep\n", encoding="utf-8")
    sidecar(served, "src.md").symlink_to(victim)
    body = {"anchor": "beta/1", "text": "x", "part": "b"}
    assert served.request("POST", COMMENTS, body)[0] == 400
    assert victim.read_text(encoding="utf-8") == "keep\n"


def test_answer_kind_is_not_open_to_the_comment_route(served: Served) -> None:
    body = {"kind": "answer", "anchor": "own", "item": "x", "value": "y"}
    assert served.request("POST", COMMENTS, body)[0] == 400
    assert untouched(served)


def test_read_reports_a_broken_include(served: Served) -> None:
    status, ok = served.request("GET", "/api/docs/notes/page.md")
    assert (status, ok["include_error"]) == (200, None)  # type: ignore[index]
    (served.working / "notes" / "src.md").unlink()
    status, doc = served.request("GET", "/api/docs/notes/page.md")
    assert status == 200 and "not found" in doc["include_error"]  # type: ignore[index]


CODE_PAGE = "# Doc\n\nProse.\n\n```py\nx = 1\n```\n"
CODE_COMMENTS = "/api/docs/notes/code.md/comments"


def suggestion(anchor: str) -> dict[str, object]:
    return {
        "anchor": anchor,
        "kind": "suggestion",
        "quote": "x = 1",
        "replacement": "y = 2",
        "text": "change",
    }


@pytest.fixture
def code_served(served: Served) -> Served:
    (served.working / "notes" / "code.md").write_text(CODE_PAGE, encoding="utf-8")
    return served


def test_kind_suggestion_on_code_is_400_and_writes_nothing(code_served: Served) -> None:
    status, body = code_served.request("POST", CODE_COMMENTS, suggestion("doc/2"))
    assert status == 400
    assert "suggestion is not allowed on code" in str(body)
    assert untouched(code_served)


def test_kind_suggestion_on_prose_is_stored(code_served: Served) -> None:
    status, _ = code_served.request("POST", CODE_COMMENTS, suggestion("doc/1"))
    assert status == 201
    assert not untouched(code_served)


def test_kind_suggestion_on_a_stale_anchor_is_400(code_served: Served) -> None:
    status, _ = code_served.request("POST", CODE_COMMENTS, suggestion("doc/9"))
    assert status == 400
    assert untouched(code_served)


def test_kind_comment_on_code_and_on_a_stale_anchor_is_stored(
    code_served: Served,
) -> None:
    for anchor in ("doc/2", "doc/9"):
        body = {"anchor": anchor, "text": "note"}
        assert code_served.request("POST", CODE_COMMENTS, body)[0] == 201
