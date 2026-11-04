"""Comments on included parts: routing, the allowlist, symlinks and concurrency."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.comments import (
    comments_path,
    fold,
    fold_with_sources,
    read_rows,
)
from varde_learn.docs.pages.include import include_sources
from varde_learn.docs.pages.store import DecisionDenied, sources_for, store_comment
from varde_learn.docs.pages.watch import comment_line, new_open_comments

SOURCE = """\
---
type: plan
status: todo
---

# Plan

Intro.

## Alpha

First.

Second.

### Inner

Deep.

## Beta {#beta-id}

Last.

## Acceptance criteria

- assert: one

## Alpha

Again.
"""


def page(*statements: str) -> str:
    return "```ui\n" + "\n".join(statements) + "\n```\n"


def inc(name: str, source: str, selector: str) -> str:
    return f'{name} = include(source: "{source}", select: "{selector}")'


OTHER = "# Other\n\nText of other.\n"


def body(**fields: Any) -> bytes:
    data = {"anchor": "beta-id/1", "text": "note", "part": "beta", **fields}
    return json.dumps({k: v for k, v in data.items() if v is not None}).encode()


def post(doc: Path, root: Path, raw: bytes, *, open_: bool = True) -> dict[str, Any]:
    sources = sources_for(doc, raw, root / "none")
    return store_comment(doc, raw, decisions_open=open_, sources=sources)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / "docs"
    base.mkdir()
    (base / "src.md").write_text(SOURCE, encoding="utf-8")
    (base / "other.md").write_text(OTHER, encoding="utf-8")
    return base


def make_page(root: Path, *statements: str, name: str = "page.md") -> Path:
    doc = root / name
    doc.write_text(page(*statements) + "\n## Own\n\nOwn text.\n", encoding="utf-8")
    return doc


@pytest.fixture
def doc(root: Path) -> Path:
    return make_page(
        root,
        inc("beta", "src.md", "heading:beta-id"),
        inc("alpha", "src.md", "heading:alpha"),
        inc("oth", "other.md", "heading:other"),
    )


def src_rows(root: Path, name: str = "src.md") -> list[dict[str, Any]]:
    return read_rows(root / name)


def test_part_comment_lands_in_the_source_sidecar_only(root: Path, doc: Path) -> None:
    row = post(doc, root, body())
    assert [r["id"] for r in src_rows(root)] == [row["id"]]
    assert read_rows(doc) == []
    assert not comments_path(doc).exists()


def test_page_owned_comment_stays_in_the_page_sidecar(root: Path, doc: Path) -> None:
    row = post(doc, root, body(part=None, anchor="own/1"))
    assert [r["id"] for r in read_rows(doc)] == [row["id"]]
    assert src_rows(root) == []


def test_multi_source_each_comment_goes_to_its_own_sidecar(
    root: Path, doc: Path
) -> None:
    a = post(doc, root, body())
    b = post(doc, root, body(part="oth", anchor="other/1"))
    own = post(doc, root, body(part=None, anchor="own"))
    assert [r["id"] for r in src_rows(root)] == [a["id"]]
    assert [r["id"] for r in src_rows(root, "other.md")] == [b["id"]]
    assert [r["id"] for r in read_rows(doc)] == [own["id"]]


def test_comment_shows_on_every_page_that_includes_the_part(
    root: Path, doc: Path
) -> None:
    row = post(doc, root, body())
    second = make_page(root, inc("b", "src.md", "heading:beta-id"), name="two.md")
    found = fold_with_sources(second, include_sources(second.read_text(), root, root))
    assert [(c["id"], c["part"]) for c in found] == [(row["id"], "b")]
    on_source = fold(read_rows(root / "src.md"))
    assert [c["id"] for c in on_source] == [row["id"]]


def test_comment_on_another_part_of_the_source_is_not_shown(
    root: Path, doc: Path
) -> None:
    post(doc, root, body(part="alpha", anchor="alpha/1"))
    second = make_page(root, inc("b", "src.md", "heading:beta-id"), name="two.md")
    sources = include_sources(second.read_text(), root, root)
    assert fold_with_sources(second, sources) == []


def test_anchor_stable_when_the_source_changes_elsewhere(root: Path, doc: Path) -> None:
    row = post(doc, root, body())
    changed = SOURCE.replace("Intro.", "Intro.\n\nAdded paragraph.\n\nAnother.")
    (root / "src.md").write_text(changed, encoding="utf-8")
    found = fold_with_sources(doc, include_sources(doc.read_text(), root, root))
    assert [(c["id"], c.get("orphaned")) for c in found] == [(row["id"], None)]


def test_orphaned_when_the_anchor_no_longer_resolves(root: Path, doc: Path) -> None:
    row = post(doc, root, body())
    (root / "src.md").write_text(
        SOURCE.replace("Last.\n", ""),
        encoding="utf-8",
    )
    found = fold_with_sources(doc, include_sources(doc.read_text(), root, root))
    # With no region left to match, every include of that source reports the orphan.
    assert {(c["id"], c.get("orphaned")) for c in found} == {(row["id"], True)}
    assert {c["part"] for c in found} == {"beta", "alpha"}
    assert [r["id"] for r in src_rows(root)] == [row["id"]]  # rows are never dropped


def test_watch_delivers_part_comments_tagged(root: Path, doc: Path) -> None:
    row = post(doc, root, body())
    fresh = new_open_comments(doc, set())
    assert [(c["id"], c["part"]) for c in fresh] == [(row["id"], "beta")]
    assert "[beta]" in comment_line({**row, "part": "beta"})


# --- rejected cases: 400 and no file written ------------------------------------


def listing(root: Path) -> list[str]:
    return sorted(p.name for p in root.rglob("*") if p.is_file())


def refuse(doc: Path, root: Path, raw: bytes, match: str | None = None) -> None:
    before = listing(root)
    with pytest.raises(ValueError, match=match):
        post(doc, root, raw)
    assert listing(root) == before


@pytest.mark.parametrize("kind", ["suggestion", "drift", "decision", "answer"])
def test_kind_with_part_is_rejected(root: Path, doc: Path, kind: str) -> None:
    extra = {"quote": "Last.", "replacement": "x", "item": "beta", "verdict": "open"}
    refuse(doc, root, body(kind=kind, value="approved", **extra), "only a comment")


def test_kind_unknown_value_is_rejected(root: Path, doc: Path) -> None:
    refuse(doc, root, body(kind="nope"))


def test_part_must_be_a_string(root: Path, doc: Path) -> None:
    refuse(doc, root, body(part=["beta"]), "part must be")


def test_allowlist_unknown_part_is_rejected(root: Path, doc: Path) -> None:
    refuse(doc, root, body(part="ghost"), "unknown part")


def test_allowlist_part_cannot_be_a_path(root: Path, doc: Path) -> None:
    for part in ("src.md", str(root / "src.md"), "../src.md"):
        refuse(doc, root, body(part=part), "unknown part")


def test_allowlist_anchor_outside_the_region_is_rejected(root: Path, doc: Path) -> None:
    refuse(doc, root, body(anchor="alpha/1"), "outside the included part")
    refuse(doc, root, body(anchor="ghost"), "outside the included part")


def test_allowlist_bad_anchor_syntax_is_rejected(root: Path, doc: Path) -> None:
    refuse(doc, root, body(anchor="../x"))
    refuse(doc, root, body(anchor="beta-id/1\n"))


def test_allowlist_dotfile_and_non_md_sources_are_never_writable(
    root: Path,
) -> None:
    (root / ".hidden.md").write_text(OTHER, encoding="utf-8")
    (root / "notes.txt").write_text(OTHER, encoding="utf-8")
    for source in (".hidden.md", "notes.txt"):
        bad = make_page(root, inc("x", source, "heading:other"), name="bad.md")
        refuse(bad, root, body(part="x", anchor="other"))
        bad.unlink()


def test_traversal_in_an_include_source_is_rejected(root: Path, tmp_path: Path) -> None:
    (tmp_path / "outside.md").write_text(OTHER, encoding="utf-8")
    bad = make_page(root, inc("x", "../outside.md", "heading:other"), name="bad.md")
    refuse(bad, root, body(part="x", anchor="other"), "must not use")
    assert not (tmp_path / "outside.md.comments.jsonl").exists()


def test_traversal_absolute_source_outside_the_roots_is_rejected(
    root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "away"
    outside.mkdir()
    (outside / "x.md").write_text(OTHER, encoding="utf-8")
    bad = make_page(root, inc("x", str(outside / "x.md"), "heading:other"), name="b.md")
    refuse(bad, root, body(part="x", anchor="other"), "outside the allowed roots")
    assert list(outside.iterdir()) == [outside / "x.md"]


def test_symlink_source_pointing_outside_is_rejected(
    root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "away"
    outside.mkdir()
    (outside / "x.md").write_text(OTHER, encoding="utf-8")
    (root / "link.md").symlink_to(outside / "x.md")
    bad = make_page(root, inc("x", "link.md", "heading:other"), name="bad.md")
    refuse(bad, root, body(part="x", anchor="other"), "outside the allowed roots")
    assert list(outside.iterdir()) == [outside / "x.md"]


def test_symlink_sidecar_is_refused_and_its_target_untouched(
    root: Path, doc: Path, tmp_path: Path
) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("keep\n", encoding="utf-8")
    comments_path(root / "src.md").symlink_to(victim)
    refuse(doc, root, body(), "not writable")
    assert victim.read_text(encoding="utf-8") == "keep\n"


def test_symlink_page_sidecar_is_refused_by_the_append(
    root: Path, doc: Path, tmp_path: Path
) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("keep\n", encoding="utf-8")
    comments_path(doc).symlink_to(victim)
    refuse(doc, root, body(part=None, anchor="own"), "not a regular file")
    assert victim.read_text(encoding="utf-8") == "keep\n"


def test_source_swapped_for_a_symlink_after_page_load_is_refused(
    root: Path, doc: Path, tmp_path: Path
) -> None:
    sources = sources_for(doc, body(), root / "none")
    outside = tmp_path / "away"
    outside.mkdir()
    (outside / "x.md").write_text(SOURCE, encoding="utf-8")
    (root / "src.md").unlink()
    (root / "src.md").symlink_to(outside / "x.md")
    with pytest.raises(ValueError, match="not writable"):
        store_comment(doc, body(), decisions_open=True, sources=sources)
    assert list(outside.iterdir()) == [outside / "x.md"]
    # and a fresh resolution refuses the new target as well
    with pytest.raises(ValueError, match="outside the allowed roots"):
        sources_for(doc, body(), root / "none")


def test_unreadable_include_is_a_400_not_a_fallback_to_the_page(
    root: Path, doc: Path
) -> None:
    (root / "src.md").unlink()
    refuse(doc, root, body(), "not found")
    assert read_rows(doc) == []


def test_part_comment_needs_text(root: Path, doc: Path) -> None:
    refuse(doc, root, body(text="  "), "empty comment text")


def test_part_without_sources_is_rejected(root: Path, doc: Path) -> None:
    with pytest.raises(ValueError, match="unknown part"):
        store_comment(doc, body(), decisions_open=True, sources=None)
    assert listing(root) == ["other.md", "page.md", "src.md"]


def test_answer_with_part_is_rejected_even_when_closed(root: Path, doc: Path) -> None:
    with pytest.raises(ValueError, match="only a comment"):
        post(doc, root, body(kind="answer", value="x"), open_=False)
    with pytest.raises(DecisionDenied):
        post(
            doc,
            root,
            body(part=None, kind="answer", value="x", item="beta"),
            open_=False,
        )


# --- append primitive -----------------------------------------------------------


def test_concurrent_part_writes_never_interleave_or_blank(
    root: Path, doc: Path
) -> None:
    second = make_page(root, inc("beta", "src.md", "heading:beta-id"), name="two.md")
    threads_n, each = 8, 25
    errors: list[BaseException] = []

    def worker(page_doc: Path, number: int) -> None:
        try:
            for i in range(each):
                text = f"w{number}-{i} " + "x" * 3000
                post(page_doc, root, body(text=text))
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    pool = [
        threading.Thread(target=worker, args=(doc if n % 2 else second, n))
        for n in range(threads_n)
    ]
    for thread in pool:
        thread.start()
    for thread in pool:
        thread.join()
    assert errors == []
    raw = comments_path(root / "src.md").read_text(encoding="utf-8")
    assert raw.endswith("\n") and "\n\n" not in raw and not raw.startswith("\n")
    lines = [line for line in raw.split("\n") if line]
    assert len(lines) == threads_n * each
    rows = [json.loads(line) for line in lines]
    assert len({r["id"] for r in rows}) == len(rows)
    assert {r["text"].split()[0] for r in rows} == {
        f"w{n}-{i}" for n in range(threads_n) for i in range(each)
    }


WRITER = """
import json, sys
from pathlib import Path
from varde_learn.docs.pages.store import sources_for, store_comment
doc, root, number = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
for i in range(20):
    raw = json.dumps({"anchor": "beta-id/1", "part": "beta",
                      "text": f"p{number}-{i} " + "y" * 4000}).encode()
    store_comment(doc, raw, decisions_open=True,
                  sources=sources_for(doc, raw, root / "none"))
"""


def test_concurrent_processes_use_one_append_each(root: Path, doc: Path) -> None:
    procs = [
        subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", WRITER, str(doc), str(root), str(n)]
        )
        for n in range(4)
    ]
    assert [p.wait(60) for p in procs] == [0] * 4
    raw = comments_path(root / "src.md").read_text(encoding="utf-8")
    assert "\n\n" not in raw
    assert len([json.loads(line) for line in raw.split("\n") if line]) == 80


def test_torn_tail_is_repaired_in_the_same_write_and_blank_lines_are_skipped(
    root: Path, doc: Path
) -> None:
    path = comments_path(root / "src.md")
    path.write_text(
        '{"id":"c1","state":"open","text":"a","anchor":"x"}', encoding="utf-8"
    )
    post(doc, root, body())
    text = path.read_text(encoding="utf-8")
    assert "\n\n" not in text and text.endswith("\n")
    assert len(src_rows(root)) == 2
    path.write_text(text + "\n\n   \n", encoding="utf-8")
    assert len(src_rows(root)) == 2


# --- review fixes -----------------------------------------------------------------


def test_source_page_state_rows_never_reach_an_including_page(
    root: Path, doc: Path
) -> None:
    from varde_learn.docs.pages.comments import append_comment, mark_latest_decisions

    for extra in (
        {"kind": "answer", "item": "ship", "value": "approved"},
        {"kind": "decision", "item": "ship", "verdict": "approved"},
        {"kind": "drift", "item": "ship", "verdict": "open"},
        {"kind": "suggestion", "replacement": "x"},
    ):
        append_comment(root / "src.md", "beta-id/1", "Last.", "s", extra=extra)
    own = append_comment(
        doc, "own", "", "mine", extra={"kind": "answer", "item": "ship", "value": "x"}
    )
    found = fold_with_sources(doc, include_sources(doc.read_text(), root, root))
    assert [c["id"] for c in found] == [own["id"]]
    [latest] = [c for c in mark_latest_decisions(found) if c["id"] == own["id"]]
    assert latest["latest"] is True
    kept = post(doc, root, body())
    found = fold_with_sources(doc, include_sources(doc.read_text(), root, root))
    assert {c["id"] for c in found} == {own["id"], kept["id"]}


def test_watch_reports_a_broken_include_once_on_stderr(
    root: Path, doc: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from varde_learn.docs.pages.watch import watch_lines

    (root / "src.md").unlink()
    ticks = iter(range(3))

    def stop_after(_: float) -> None:
        if next(ticks) == 2:
            raise KeyboardInterrupt

    lines = watch_lines(doc, "1s", sleep=stop_after)
    with pytest.raises(KeyboardInterrupt):
        list(lines)
    assert capsys.readouterr().err.count("include error:") == 1
