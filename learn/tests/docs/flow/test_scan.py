from pathlib import Path

from varde_learn.docs.flow.model import EdgeKind, External, ExternalType, Runs
from varde_learn.docs.flow.scan import (
    CLAUSE,
    END,
    HANDOFF,
    Pointer,
    SkillDir,
    blocks,
    matches,
    normpath,
    resolve,
    scan,
    sentence_at,
    short,
    short_to,
    targets,
)


def raws(line: str, fenced: bool) -> list[str]:
    return [target.raw for target in targets(line, fenced)]


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def scan_text(tmp_path: Path, skill_md: str, rel: str, text: str):
    skill = tmp_path / "demo"
    write(skill, "SKILL.md", skill_md)
    write(skill, rel, text)
    for name in ("a", "b", "c"):
        write(skill, f"references/{name}.md", "x")
    return scan(SkillDir(skill), rel, set())


def test_path_lookbehind_needs_a_boundary_before_the_directory():
    assert raws("`see references/a.md`", False) == ["references/a.md"]
    assert raws("`../assets/b.png`", False) == ["assets/b.png"]
    assert raws("`(scripts/c.sh)`", False) == ["scripts/c.sh"]
    assert raws("`xreferences/a.md`", False) == []


def test_script_lookbehind_needs_a_boundary_in_fenced_lines():
    assert raws("python3 scripts/run.py --x", True) == ["scripts/run.py"]
    assert raws("./scripts/run.py", True) == ["scripts/run.py"]
    assert raws("myscripts/run.py", True) == []
    assert raws("cat references/a.md", True) == []


def test_end_lookahead_needs_whitespace_after_the_stop():
    text = "Read v1.5 first. Then stop."
    assert sentence_at(text, 0, END) == "Read v1.5 first."
    assert sentence_at(text, 20, END) == " Then stop."


def test_clause_lookahead_ends_at_a_semicolon_before_whitespace():
    text = "Read a; then b; keep a;b. Done."
    assert sentence_at(text, 0, CLAUSE) == "Read a;"
    assert sentence_at(text, 9, CLAUSE) == " then b;"
    assert sentence_at(text, 17, CLAUSE) == " keep a;b."


def test_handoff_negative_lookahead_skips_instead_of():
    assert not matches(HANDOFF, "use this instead of that")
    assert matches(HANDOFF, "do this instead.")
    assert matches(HANDOFF, "then continue with the plan")


def test_normpath_collapses_dots_like_posix():
    assert normpath("references/../scripts/./a.sh") == "scripts/a.sh"
    assert normpath("../a.md") == "../a.md"
    assert normpath("a//b") == "a/b"
    assert normpath(".") == "."


def test_resolve_tries_each_enclosing_folder_for_a_path_and_one_for_a_link(
    tmp_path: Path,
):
    skill = tmp_path / "demo"
    write(skill, "SKILL.md", "x")
    write(skill, "references/a/b.md", "x")
    write(skill, "references/top.md", "x")
    directory = SkillDir(skill)

    def found(source: str, raw: str, link: bool) -> tuple[str | None, bool]:
        return resolve(directory, source, raw, link)

    assert found("references/a/c.md", "references/top.md", False) == (
        "references/top.md",
        False,
    )
    assert found("references/a/c.md", "b.md#intro", True) == (
        "references/a/b.md",
        False,
    )
    assert found("references/a/c.md", "top.md", True) == ("references/a/top.md", False)
    assert found("SKILL.md", "references/<x>.md", False) == (None, True)
    assert found("SKILL.md", "references/dir/", False) == (None, True)
    assert found("SKILL.md", "../out.md", True) == (None, True)


def test_blocks_group_lines_and_mark_case_and_role_headings():
    lines = [
        "# Title",
        "## If stale",
        "Read `references/a.md`.",
        "second line",
        "",
        "| a | b |",
        "## The reviewer",
        "- one",
        "```sh",
        "run scripts/x.sh",
        "```",
    ]
    found = blocks(lines)
    summary = [(len(b.lines), b.case, b.role, b.table, b.fenced) for b in found]
    assert summary == [
        (2, True, False, False, False),
        (1, True, False, True, False),
        (1, False, True, False, False),
        (1, False, True, False, True),
    ]
    assert found[2].heading == "The reviewer"


def test_classifies_load_handoff_mention_and_role_pointers(tmp_path: Path):
    text = (
        "Read `references/a.md`.\n\nThen continue with `references/b.md`.\n\n"
        "The tool `references/c.md` exists.\n\n"
        "The reviewer reads `references/a.md`.\n\n"
        "Use `references/b.md` when stale.\n"
    )
    found = scan_text(tmp_path, "x", "references/x.md", text)
    got = [
        (x.body.to, x.body.kind, x.body.conditional)
        for x in found
        if isinstance(x.body, Pointer)
    ]
    assert got == [
        ("references/a.md", EdgeKind.LOAD, False),
        ("references/b.md", EdgeKind.HANDOFF, False),
        ("references/c.md", EdgeKind.MENTION, False),
        ("references/a.md", EdgeKind.ROLE, False),
        ("references/b.md", EdgeKind.LOAD, True),
    ]


def test_a_table_row_outside_skill_md_is_a_conditional_load(tmp_path: Path):
    found = scan_text(
        tmp_path,
        "x",
        "references/x.md",
        "| Case | Read |\n|---|---|\n| One | `references/a.md` |\n",
    )
    assert [
        (x.body.to, x.body.kind, x.body.conditional)
        for x in found
        if isinstance(x.body, Pointer)
    ] == [("references/a.md", EdgeKind.LOAD, True)]


def test_finds_inline_skill_modes_with_a_route_qualifier(tmp_path: Path):
    found = [
        x.body
        for x in scan_text(
            tmp_path,
            "x",
            "references/x.md",
            "Run `varde-build` build via its builder route.\n",
        )
        if isinstance(x.body, External)
    ]
    assert len(found) == 1
    assert found[0].target == "varde-build build"
    assert found[0].kind == EdgeKind.LOAD
    assert found[0].qualifier == "builder"


def test_a_dispatch_takes_the_file_named_after_for(tmp_path: Path):
    found = [
        x.body
        for x in scan_text(
            tmp_path,
            "x",
            "references/x.md",
            "Dispatch a builder for `references/a.md`.\n",
        )
        if isinstance(x.body, External)
    ]
    assert len(found) == 1
    assert found[0].external == ExternalType.AGENT
    assert found[0].target == "builder"
    assert found[0].runs == Runs(file="references/a.md")


def test_an_independent_report_span_is_a_review_dispatch(tmp_path: Path):
    found = [
        x.body
        for x in scan_text(
            tmp_path,
            "x",
            "references/x.md",
            "Run an independent `varde-review report` on the diff.\n",
        )
        if isinstance(x.body, External)
    ]
    assert len(found) == 1
    assert found[0].target == "review"
    assert found[0].report_order
    assert found[0].runs == Runs(skill="varde-review", mode="report")


def test_short_trims_markup_and_ellipsizes():
    assert short("**Bold** `code`") == "Bold code"
    assert short_to("abcdefghij", 8) == "abcde..."
