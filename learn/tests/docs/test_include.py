from pathlib import Path

import pytest
from varde_learn.docs.pages import blocks
from varde_learn.docs.pages.include import (
    IncludeError,
    include_errors,
    include_sources,
    resolve_includes,
)
from varde_learn.docs.pages.select import SelectorError, select

FIXTURES = Path(__file__).parent / "fixtures"

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

TASK = """\
---
type: task
---

Task body

#### Acceptance criteria

- assert: task one

#### Progress

none
"""


def page(*statements: str) -> str:
    return "```ui\n" + "\n".join(statements) + "\n```\n"


def inc(name: str, source: str, selector: str) -> str:
    return f'{name} = include(source: "{source}", select: "{selector}")'


@pytest.fixture
def root(tmp_path: Path) -> Path:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    (doc_root / "src.md").write_text(SOURCE, encoding="utf-8")
    return doc_root


@pytest.fixture
def store(tmp_path: Path) -> Path:
    plans = tmp_path / "plans"
    (plans / "p" / "tasks").mkdir(parents=True)
    (plans / "p" / "plan.md").write_text(SOURCE, encoding="utf-8")
    (plans / "p" / "tasks" / "t-one.md").write_text(TASK, encoding="utf-8")
    return plans


# --- select -----------------------------------------------------------------


def test_select_heading_runs_to_next_heading_of_equal_or_higher_level() -> None:
    out = select(SOURCE, "heading:alpha")
    assert out.startswith("## Alpha") and "### Inner" in out and "Deep." in out
    assert "Beta" not in out


def test_select_nth_block_under_a_heading() -> None:
    assert select(SOURCE, "heading:alpha/2") == "Second."


def test_select_repeated_heading_takes_the_suffixed_anchor() -> None:
    assert select(SOURCE, "heading:alpha-2") == "## Alpha\n\nAgain."


def test_select_explicit_id_heading() -> None:
    assert select(SOURCE, "heading:beta-id").endswith("Last.")


def test_select_acceptance_in_plan_and_task() -> None:
    assert select(SOURCE, "acceptance") == "## Acceptance criteria\n\n- assert: one"
    assert (
        select(TASK, "acceptance") == "#### Acceptance criteria\n\n- assert: task one"
    )


def test_select_frontmatter() -> None:
    assert select(SOURCE, "frontmatter") == "---\ntype: plan\nstatus: todo\n---"


def test_select_lines_widens_to_whole_blocks() -> None:
    assert select(SOURCE, "lines:10-10") == "## Alpha"
    assert select(SOURCE, "lines:12-14") == "First.\n\nSecond."


@pytest.mark.parametrize(
    "selector",
    [
        "",
        "heading:",
        "heading:Bad Slug",
        "lines:5-2",
        "lines:0-3",
        "nope:x",
        "task:a/b",
    ],
)
def test_select_rejects_malformed_selectors(selector: str) -> None:
    with pytest.raises(SelectorError):
        select(SOURCE, selector)


def test_select_reports_missing_targets() -> None:
    for selector in ("heading:missing", "lines:900-901"):
        with pytest.raises(SelectorError):
            select(SOURCE, selector)
    with pytest.raises(SelectorError, match="frontmatter"):
        select("# Only\n", "frontmatter")


# --- anchors ----------------------------------------------------------------


def anchors(html: str) -> list[str]:
    import re

    return re.findall(r'data-anchor="([^"]+)"', html)


def test_anchor_tags_blocks_with_source_anchor_and_part_id(root: Path) -> None:
    text = page(inc("a", "src.md", "heading:alpha"))
    part = resolve_includes(text, root, root / "none")["a"]
    assert anchors(part.html) == ["alpha", "alpha/1", "alpha/2", "inner", "inner/1"]
    assert part.html.count('data-part="a"') == 6  # section plus five blocks


def test_anchor_explicit_id_wins_over_slug(root: Path) -> None:
    part = resolve_includes(page(inc("b", "src.md", "heading:beta-id")), root, root)[
        "b"
    ]
    assert anchors(part.html) == ["beta-id", "beta-id/1"]
    assert "{#" not in part.html


def test_anchor_repeated_headings_get_numbered_suffixes(root: Path) -> None:
    part = resolve_includes(page(inc("c", "src.md", "heading:alpha-2")), root, root)[
        "c"
    ]
    assert anchors(part.html)[0] == "alpha-2"


def test_anchor_stable_when_text_changes_outside_the_part(root: Path) -> None:
    text = page(inc("a", "src.md", "heading:alpha/2"))
    before = resolve_includes(text, root, root)["a"]
    edited = "Preface.\n\n## Extra\n\nMore.\n\n" + SOURCE.replace(
        "Last.", "Last!\n\nTail."
    )
    (root / "src.md").write_text(edited, encoding="utf-8")
    after = resolve_includes(text, root, root)["a"]
    assert anchors(before.html) == anchors(after.html) == ["alpha/2"]
    assert before.markdown == after.markdown == "Second."


def test_anchor_duplicate_explicit_heading_id_is_reported() -> None:
    doc = "## A {#same}\n\n## B {#same}\n\n## C {#Bad_Id}\n"
    rules = [(e.line, e.rule) for e in blocks.check(doc)]
    assert rules == [(3, "heading-id-duplicate"), (5, "heading-id-invalid")]


def test_anchor_ignores_ids_inside_code_fences() -> None:
    assert blocks.check("```md\n## A {#same}\n\n## B {#same}\n```\n") == []


# --- sources ----------------------------------------------------------------


def test_sources_map_id_to_confined_path_and_region(root: Path) -> None:
    text = page(inc("a", "src.md", "heading:beta-id"), inc("t", "src.md", "acceptance"))
    found = include_sources(text, root, root / "none")
    assert found["a"].path == (root / "src.md").resolve()
    start, end = found["a"].start, found["a"].end
    assert SOURCE.splitlines()[start] == "## Beta {#beta-id}"
    assert SOURCE.splitlines()[end - 1] == "Last."
    assert found["t"].start == SOURCE.splitlines().index("## Acceptance criteria")


def test_sources_plan_store_task_selector_reads_the_task_file(
    root: Path, store: Path
) -> None:
    source = store / "p" / "plan.md"
    text = page(
        f'x = include(source: "{source}", select: "task:t-one")',
        f'y = include(source: "{source}", select: "acceptance")',
    )
    found = include_sources(text, root, store)
    assert found["x"].path == (store / "p" / "tasks" / "t-one.md").resolve()
    assert found["y"].path == source.resolve()
    assert "Task body" in resolve_includes(text, root, store)["x"].markdown


def test_sources_html_is_escaped_never_raw(root: Path) -> None:
    (root / "src.md").write_text("## H\n\n<script>alert(1)</script> **b**\n", "utf-8")
    out = resolve_includes(page(inc("a", "src.md", "heading:h")), root, root)["a"].html
    assert "<script>" not in out and "&lt;script&gt;" in out and "<strong>b" in out


def test_sources_inputs_and_custom_fences_are_inert(root: Path) -> None:
    body = (
        '## H\n\n```ui id=d\nd = decision(question: "q", options: ["approve"])\n```\n\n'
    )
    body += "```custom\n<script>x</script>\n```\n"
    (root / "src.md").write_text(body, "utf-8")
    out = resolve_includes(page(inc("a", "src.md", "heading:h")), root, root)["a"].html
    assert "<button disabled" in out and "<button data" not in out
    assert "<iframe" not in out and "&lt;script&gt;" in out


# --- confinement ------------------------------------------------------------


@pytest.mark.parametrize("source", ["../src.md", "a/../../src.md", "x/../src.md"])
def test_traversal_is_rejected(root: Path, source: str) -> None:
    with pytest.raises(IncludeError, match="'..'"):
        include_sources(page(inc("a", source, "acceptance")), root, root)


def test_traversal_absolute_path_outside_roots_is_rejected(
    root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "out.md"
    outside.write_text(SOURCE, "utf-8")
    text = page(inc("a", str(outside), "acceptance"))
    with pytest.raises(IncludeError, match="outside the allowed roots"):
        include_sources(text, root, tmp_path / "plans")


def test_symlink_escaping_the_roots_is_rejected(root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "out.md"
    outside.write_text(SOURCE, "utf-8")
    (root / "link.md").symlink_to(outside)
    (root / "dir").symlink_to(tmp_path)
    for source in ("link.md", "dir/out.md"):
        with pytest.raises(IncludeError, match="outside the allowed roots"):
            include_sources(page(inc("a", source, "acceptance")), root, root / "x")


def test_symlink_inside_the_roots_is_allowed(root: Path) -> None:
    (root / "alias.md").symlink_to(root / "src.md")
    found = include_sources(page(inc("a", "alias.md", "acceptance")), root, root)
    assert found["a"].path == (root / "src.md").resolve()


def test_symlink_to_a_dotfile_inside_the_roots_is_rejected(root: Path) -> None:
    (root / ".hidden.md").write_text(SOURCE, "utf-8")
    (root / "alias.md").symlink_to(root / ".hidden.md")
    with pytest.raises(IncludeError, match="not includable"):
        include_sources(page(inc("a", "alias.md", "acceptance")), root, root)


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        ".git/x.md",
        ".varde/x.md",
        "a.env.md",
        "my-secret.md",
        "credentials.md",
        "token.md",
    ],
)
def test_dotfile_and_secret_names_are_never_includable(root: Path, name: str) -> None:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(SOURCE, "utf-8")
    with pytest.raises(IncludeError):
        include_sources(page(inc("a", name, "acceptance")), root, root)


def test_dotfile_rule_applies_below_the_root_not_to_the_root_itself(
    tmp_path: Path,
) -> None:
    hidden_root = tmp_path / ".docs"
    hidden_root.mkdir()
    (hidden_root / "src.md").write_text(SOURCE, "utf-8")
    found = include_sources(
        page(inc("a", "src.md", "acceptance")), hidden_root, hidden_root
    )
    assert "a" in found


def test_source_must_be_a_regular_md_file(root: Path) -> None:
    (root / "notes.txt").write_text("x", "utf-8")
    (root / "folder.md").mkdir()
    for name in ("notes.txt", "folder.md", "missing.md"):
        with pytest.raises(IncludeError):
            include_sources(page(inc("a", name, "acceptance")), root, root)


# --- cycles and depth -------------------------------------------------------


def test_cycle_or_repeat_of_source_and_selector_is_an_error(root: Path) -> None:
    text = page(inc("a", "src.md", "acceptance"), inc("b", "./src.md", "acceptance"))
    with pytest.raises(IncludeError, match="repeats"):
        resolve_includes(text, root, root)


def test_cycle_repeated_include_id_is_an_error(root: Path) -> None:
    text = page(inc("a", "src.md", "acceptance")) + page(
        inc("a", "src.md", "frontmatter")
    )
    with pytest.raises(IncludeError, match="repeated"):
        resolve_includes(text, root, root)


def test_cycle_same_source_different_selectors_is_fine(root: Path) -> None:
    text = page(inc("a", "src.md", "acceptance"), inc("b", "src.md", "frontmatter"))
    assert set(resolve_includes(text, root, root)) == {"a", "b"}


def test_depth_include_inside_an_included_source_is_not_expanded(root: Path) -> None:
    nested = (
        "## H\n\n```ui\ninner = "
        + 'include(source: "src.md", select: "acceptance")\n```\n'
    )
    (root / "nested.md").write_text(nested, "utf-8")
    text = page(inc("a", "nested.md", "heading:h"))
    part = resolve_includes(text, root, root)["a"]
    assert 'data-part="inner"' not in part.html and "&quot;src.md&quot;" in part.html
    assert part.nested
    errors = include_errors(text, root, root)
    assert [(line, rule) for line, rule, _ in errors] == [(2, "include-nested")]


# --- statements and learn check ---------------------------------------------


def test_statement_props_are_validated() -> None:
    bad = page(
        'a = include(source: "x.md")', 'b = include(source: "x.md", select: "zz")'
    )
    rules = [rule for _, rule, _ in include_errors(bad)]
    assert rules == ["missing-key", "selector"]
    extra = page('a = include(source: "x.md", select: "frontmatter", nope: 1)')
    assert [r for _, r, _ in include_errors(extra)] == ["unknown-key"]


def test_check_reports_unresolvable_include_with_a_root(root: Path) -> None:
    text = page(inc("a", "gone.md", "acceptance"))
    assert blocks.check(text) == []  # no root: statements only
    errors = blocks.check(text, root)
    assert [e.rule for e in errors] == ["include"] and errors[0].line == 2


def test_check_ui_fence_parse_errors_and_other_components_are_checked() -> None:
    errors = blocks.check("```ui\nx = bogus(a: 1)\ny = include(\n```\n")
    assert errors[0].rule == "component-unknown"
    assert len(errors) == 2


def test_page_include_fixture_checks_clean() -> None:
    text = (FIXTURES / "page-include.md").read_text(encoding="utf-8")
    assert blocks.check(text, FIXTURES) == []
    parts = resolve_includes(text, FIXTURES, FIXTURES)
    assert set(parts) == {"crit", "notes"}


def test_check_blocks_cli_fails_on_a_missing_include_source(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from varde_learn.docs.pages import cli

    doc = root / "page.md"
    doc.write_text(page(inc("a", "gone.md", "acceptance")), encoding="utf-8")
    assert cli.check_blocks(doc) == 1
    assert "include" in capsys.readouterr().out
    doc.write_text(page(inc("a", "src.md", "heading:missing")), encoding="utf-8")
    assert cli.check_blocks(doc) == 1
    doc.write_text(page(inc("a", "src.md", "acceptance")), encoding="utf-8")
    assert cli.check_blocks(doc) == 0


def test_include_is_a_registered_component_with_one_validator() -> None:
    from varde_learn.docs.pages.blocks import COMPONENT_SPECS, check_props
    from varde_learn.docs.pages.blocks_render import COMPONENTS

    assert "include" in COMPONENT_SPECS and COMPONENTS["include"].answer_schema is None
    assert check_props("include", {"source": "a.md", "select": "acceptance"}, 1) == []
    assert [e.rule for e in check_props("include", {"source": "a.md"}, 1)] == [
        "missing-key"
    ]
    bad = page('a = include(source: "x.md", select: "zz")')
    assert [e.rule for e in blocks.check(bad)] == ["selector"]  # reported once


def test_source_read_is_capped_and_refuses_a_swapped_symlink(root: Path) -> None:
    from varde_learn.docs.pages import include as include_module

    (root / "big.md").write_text("x" * (include_module.MAX_SOURCE_BYTES + 5), "utf-8")
    with pytest.raises(IncludeError, match="too large"):
        resolve_includes(page(inc("a", "big.md", "lines:1-1")), root, root)
    link = root / "link.md"
    link.symlink_to(root / "src.md")
    with pytest.raises(IncludeError, match="unreadable"):
        include_module._read(link, 1)


def test_dotfile_absolute_path_above_the_root_is_allowed(tmp_path: Path) -> None:
    hidden = tmp_path / ".store" / "docs"
    hidden.mkdir(parents=True)
    (hidden / "src.md").write_text(SOURCE, "utf-8")
    text = page(inc("a", str(hidden / "src.md"), "acceptance"))
    assert "a" in include_sources(text, hidden, hidden)


def test_secret_like_task_ids_are_refused_by_design(store: Path) -> None:
    (store / "p" / "tasks" / "im-token-refresh.md").write_text(TASK, "utf-8")
    plan = store / "p" / "plan.md"
    text = page(f'x = include(source: "{plan}", select: "task:im-token-refresh")')
    with pytest.raises(IncludeError, match="not includable"):
        include_sources(text, store, store)


def test_included_widget_and_decision_fences_stay_inert(root: Path) -> None:
    body = '## H\n\n```ui\nc = choice(options: ["a"])\n```\n\n'
    body += '```ui id=d\nd = decision(question: "q", options: ["approve"])\n```\n'
    (root / "src.md").write_text(body, "utf-8")
    out = resolve_includes(page(inc("a", "src.md", "heading:h")), root, root)["a"].html
    for live in ("<button ", "<input", "<select", "data-answer"):
        assert live not in out.replace("<button disabled ", "")


def test_anchor_repeated_explicit_ids_are_reported_by_check() -> None:
    doc = "## A {#x}\n\n## B {#x}\n\n## C {#x-2}\n"
    assert [(e.line, e.rule) for e in blocks.check(doc)] == [
        (3, "heading-id-duplicate")
    ]


def test_part_blocks_carry_block_type_and_unique_stable_ids(root: Path) -> None:
    import re

    text = page(
        inc("a", "src.md", "heading:alpha"), inc("b", "src.md", "heading:beta-id")
    )
    first = resolve_includes(text, root, root / "none")
    again = resolve_includes(text, root, root / "none")
    ids_a = re.findall(r'<div class="block[^"]*" id="([^"]+)"', first["a"].html)
    ids_b = re.findall(r'<div class="block[^"]*" id="([^"]+)"', first["b"].html)
    assert ids_a[:2] == ["blk-a:alpha", "blk-a:alpha/1"]
    assert ids_b == ["blk-b:beta-id", "blk-b:beta-id/1"]
    assert len(set(ids_a)) == len(ids_a)
    assert ids_a == re.findall(r'<div class="block[^"]*" id="([^"]+)"', again["a"].html)
    assert first["a"].html.count('data-block-type="part"') == 5


def test_part_menu_offers_comment_only_and_server_refuses_suggest(root: Path) -> None:
    import json

    from varde_learn.docs.pages.actions import kind_allowed, menu_entries
    from varde_learn.docs.pages.store import store_comment

    assert menu_entries("part", allow_edit=True, in_part=True) == (
        "comment",
        "copy",
        "copy-link",
    )
    assert kind_allowed("part", "comment")
    assert not kind_allowed("part", "suggestion")
    doc = root / "page.md"
    doc.write_text(page(inc("a", "src.md", "heading:alpha")))
    body = json.dumps(
        {
            "anchor": "alpha",
            "quote": "q",
            "text": "x",
            "kind": "suggestion",
            "part": "a",
            "replacement": "y",
        }
    ).encode()
    sources = include_sources(doc.read_text(), root)
    with pytest.raises(ValueError, match="only a comment"):
        store_comment(doc, body, decisions_open=False, sources=sources)
