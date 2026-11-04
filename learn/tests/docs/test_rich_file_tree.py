"""The file-tree block: folding, order, renames, faults, escaping and code links."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks import check_props, type_text
from varde_learn.docs.pages.blocks_render.file_tree import (
    compact,
    fold,
    match_target,
    render_file_tree,
    summary_text,
)
from varde_learn.docs.pages.render import render_page

FIXTURES = Path(__file__).parent / "fixtures" / "widgets"
HOSTILE = '<img src=x onerror=alert(1)> "q" &amp; <script>alert(1)</script>'


def tree(*entries: dict[str, Any], **extra: object) -> dict[str, object]:
    return {"entries": list(entries), **extra}


def rules(data: dict[str, object]) -> list[str]:
    return [e.rule for e in check_props("file-tree", data, 1)]


def test_fold_nests_paths_and_orders_folders_before_files() -> None:
    root = fold(
        [{"path": "b.py"}, {"path": "z/x.py"}, {"path": "a/y.py"}, {"path": "A.py"}]
    )
    assert sorted(root.folders) == ["a", "z"]
    assert sorted(root.files) == ["A.py", "b.py"]
    assert root.count() == 4


def test_single_child_chain_is_compacted() -> None:
    root = fold([{"path": "a/b/c/d.py"}, {"path": "a/b/c/e.py"}])
    shown = compact(root.folders["a"])
    assert (shown.name, shown.path) == ("a/b/c", "a/b/c")
    assert list(shown.files) == ["d.py", "e.py"]


def test_renamed_entry_sits_at_new_path_and_shows_was() -> None:
    html = render_file_tree(
        tree({"path": "src/new.py", "change": "renamed", "was": "src/old.py"})
    )
    assert "src/old.py" in html and 'data-file="src/new.py"' in html
    assert "&rarr;" in html and "renamed" in html


def test_duplicate_path_is_a_fault() -> None:
    data = tree({"path": "a/b.py"}, {"path": "a/b.py"})
    assert "duplicate-path" in rules(data)
    with pytest.raises(ValueError):
        fold(data["entries"])  # type: ignore[arg-type]


def test_file_and_folder_clash_is_a_fault() -> None:
    assert "path" in rules(tree({"path": "a"}, {"path": "a/b.py"}))


@pytest.mark.parametrize("path", ["/a.py", "a//b.py", "a/", "a/../b.py", "./a.py", ""])
def test_bad_paths_are_faults(path: str) -> None:
    assert rules(tree({"path": path}))


def test_props_are_validated() -> None:
    assert rules(tree({"path": "a.py"}, collapse=2, title="t")) == []
    assert rules(tree({"path": "a.py"}, collapse=-1))
    assert rules(tree({"path": "a.py"}, collapse=True))
    assert rules(tree({"path": "a.py", "change": "bogus"}))
    assert rules(tree({"path": "a.py", "change": "renamed"}))  # needs was
    assert rules(tree({"path": "a.py", "extra": 1}))
    assert rules({"entries": []})


def test_summary_counts_equal_entries() -> None:
    entries = [
        {"path": "a", "change": "added"},
        {"path": "b", "change": "added"},
        {"path": "c", "change": "removed"},
        {"path": "d"},
    ]
    assert summary_text(entries) == "4 files: 2 added, 1 removed, 1 unchanged"
    assert summary_text(entries[:1]) == "1 file: 1 added"


def test_summary_line_in_html_equals_entry_count() -> None:
    entries = [{"path": f"d{i % 3}/f{i}.py", "change": "modified"} for i in range(30)]
    html = render_file_tree(tree(*entries))
    assert "30 files: 30 modified" in html
    assert html.count('role="treeitem" aria-label="modified') == 30


def test_collapse_closes_deeper_folders_only() -> None:
    entries = [{"path": "a/b/c/x.py"}, {"path": "a/b/y.py"}, {"path": "a/z.py"}]
    html = render_file_tree(tree(*entries, collapse=1))
    opens = re.findall(r"<details( open)?>", html)
    assert opens == [" open", "", ""]  # a open; a/b and a/b/c closed
    assert "<details>" not in render_file_tree(tree(*entries))


def test_twelve_levels_cap_the_indent_and_keep_the_full_path() -> None:
    path = "/".join(f"l{i}" for i in range(12))
    entries = [{"path": f"{path}/f.py"}, {"path": "l0/side.py"}]
    entries += [
        {"path": "/".join(f"l{j}" for j in range(i)) + "/s.py"} for i in range(2, 12)
    ]
    html = render_file_tree(tree(*entries))
    assert "vd-file-tree-flat" in html
    assert f'aria-label="{path}/f.py"' in html


def test_five_hundred_entries_render() -> None:
    entries = [
        {"path": f"p{i % 25}/q{i % 7}/f{i}.py", "change": "added"} for i in range(500)
    ]
    html = render_file_tree(tree(*entries))
    assert html.count('role="treeitem" aria-label="added') == 500
    assert "500 files: 500 added" in html


def test_hostile_text_is_escaped() -> None:
    html = render_file_tree(
        tree(
            {
                "path": f"{HOSTILE}/f.py",
                "change": "renamed",
                "was": HOSTILE,
                "note": HOSTILE,
                "role": HOSTILE,
            },
            title=HOSTILE,
        )
    )
    assert "<img" not in html and "<script" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_copy_text_is_an_indented_list_with_glyphs() -> None:
    html = render_file_tree(
        tree(
            {"path": "src/a.py", "change": "added"},
            {"path": "src/b.py", "change": "renamed", "was": "src/c.py"},
            {"path": "top.md"},
        )
    )
    copy = re.search(r'data-copy="([^"]*)"', html)
    assert copy
    assert "src/\n  + a.py\n  -&gt; b.py (was src/c.py)\ntop.md" in copy.group(1)


def test_accessibility_shape() -> None:
    html = render_file_tree(tree({"path": "a/b.py", "change": "added", "note": "n"}))
    assert 'role="tree" aria-label="Changed files"' in html
    assert 'class="vb file-tree vd-file-tree"' in html
    assert "<summary" in html and "style=" not in html and "<script" not in html


def test_match_target_prefers_the_exact_then_the_longest_tail() -> None:
    titles = {"queue.py": "top/1", "src/queue.py": "top/2", "x.py": "top/3"}
    assert match_target("src/queue.py", titles) == "top/2"
    assert match_target("lib/src/queue.py", titles) == "top/2"
    assert match_target("lib/queue.py", titles) == "top/1"
    assert match_target("src/equeue.py", titles) == ""


def test_file_links_to_the_code_block_with_that_title() -> None:
    page = render_page((FIXTURES / "rich-file-tree.md").read_text(), "d").body
    link = re.search(r'<a class="vd-file-tree-link" href="#([^"]+)">queue.py</a>', page)
    assert link
    assert f'id="{link.group(1)}"' in page
    assert page.count("vd-file-tree-link") == 1  # only the file with a code block


def test_file_tree_without_a_code_block_has_no_links() -> None:
    page = render_page(
        '```ui\nf = file-tree(entries: [{"path": "a/b.py"}])\n```\n', "d"
    ).body
    assert "vd-file-tree-link" not in page and "vd-file-tree-leaf" in page


def test_fixtures_render_without_errors() -> None:
    for name in ("rich-file-tree.md", "rich-file-tree-stress.md"):
        body = render_page((FIXTURES / name).read_text(), name).body
        assert "vb file-tree" in body and "error" not in body.lower().split("<")[0]
        assert "<script" not in body


def test_help_text_lists_the_props() -> None:
    text = type_text("file-tree")
    assert text.startswith("file-tree - ") and "collapse" in text and "entries" in text
