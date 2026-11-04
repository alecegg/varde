import json
import time
from pathlib import Path

from varde_core.text_audit import (
    Finding,
    Rule,
    Severity,
    audit,
    eval_content,
    expand_skill_dir,
    skill_refs,
    skill_spec,
)


def words(count: int) -> str:
    return " ".join(["word"] * count)


def sentence_block(count: int) -> str:
    return " ".join(["Short one."] * count)


def only(findings: list[Finding], rule: Rule) -> list[tuple[int, Severity, str]]:
    return [(f.line, f.severity, f.message) for f in findings if f.rule is rule]


def prose_doc(prose: int, other: int) -> str:
    items = ["- word"] * (other // 2)
    return f"{words(prose)}\n\n{'\n'.join(items)}\n"


def test_unit_thresholds_and_nested_list_unit() -> None:
    assert only(audit(sentence_block(3), "a.md"), Rule.UNIT) == []
    assert only(audit(sentence_block(4), "a.md"), Rule.UNIT) == [
        (1, Severity.WARN, "(unit, 4 sentences)")
    ]
    assert only(audit(sentence_block(6), "a.md"), Rule.UNIT) == [
        (1, Severity.ERROR, "(unit, 6 sentences)")
    ]
    nested = f"- {sentence_block(2)}\n  - {sentence_block(2)}\n"
    assert only(audit(nested, "a.md"), Rule.UNIT) == [
        (1, Severity.WARN, "(unit, 4 sentences)")
    ]


def test_section_thresholds_and_frontmatter_line() -> None:
    assert only(audit(f"# T\n{words(250)}\n", "a.md"), Rule.SECTION) == []
    assert only(audit(f"# T\n{words(251)}\n", "a.md"), Rule.SECTION) == [
        (1, Severity.WARN, "(section, 251 words)")
    ]
    assert only(audit(f"# T\n{words(401)}\n", "a.md"), Rule.SECTION) == [
        (1, Severity.ERROR, "(section, 401 words)")
    ]
    frontmatter = f"---\nname: x\n---\n# T\n{words(251)}\n"
    assert only(audit(frontmatter, "a.md"), Rule.SECTION)[0][0] == 4


def test_prose_share_thresholds_and_minimum() -> None:
    hint = "; steps or lists written as sentences?"
    assert only(audit(prose_doc(60, 90), "a.md"), Rule.PROSE_SHARE) == []
    assert only(audit(prose_doc(62, 88), "a.md"), Rule.PROSE_SHARE) == [
        (1, Severity.WARN, f"(prose share, 41 percent){hint}")
    ]
    assert only(audit(prose_doc(92, 58), "a.md"), Rule.PROSE_SHARE) == [
        (1, Severity.ERROR, f"(prose share, 61 percent){hint}")
    ]
    assert only(audit(words(100), "a.md"), Rule.PROSE_SHARE) == []


def test_inline_list_vectors() -> None:
    hint = "; put one item per line under a lead-in"
    assert only(
        audit("Use red, green, blue, and gold.\n", "a.md"), Rule.INLINE_LIST
    ) == [(1, Severity.WARN, f"(inline list, 4 items){hint}")]
    assert only(audit("Use red, green, and blue.\n", "a.md"), Rule.INLINE_LIST) == []
    assert only(
        audit("Use red, green, and a deep blue sea.\n", "a.md"), Rule.INLINE_LIST
    ) == [(1, Severity.WARN, f"(inline list, 3 items){hint}")]
    # A later series must be found even when the first conjunction comes
    # before the minimum two commas required by the Rust series regex.
    assert only(audit("Use a, and b, c, d, and e.\n", "a.md"), Rule.INLINE_LIST) == [
        (1, Severity.WARN, f"(inline list, 5 items){hint}")
    ]


def _fastest_audit(text: str) -> float:
    best = float("inf")
    for _ in range(3):
        started = time.perf_counter()
        audit(text, "large.md")
        best = min(best, time.perf_counter() - started)
    return best


def test_inline_list_scan_has_linear_timing_guard() -> None:
    adversarial = "Use " + ", ".join(["word"] * 200) + " end\n"
    late_conjunction = "Use " + ", ".join(["word"] * 200) + " and last.\n"
    elapsed = _fastest_audit(adversarial) + _fastest_audit(late_conjunction)
    assert elapsed < 2.0


def test_layout_vectors() -> None:
    assert only(audit("- item\nlazy\n", "a.md"), Rule.LAYOUT) == [
        (2, Severity.WARN, "(lazy continuation; indent it under its item)")
    ]
    assert only(audit("text\n</content>\n", "a.md"), Rule.LAYOUT) == [
        (2, Severity.WARN, "(stray </content> line)")
    ]
    assert only(audit("- item\n  fine\n", "a.md"), Rule.LAYOUT) == []


def test_fences_stripping_crlf_and_finding_fields() -> None:
    assert audit(f"```\n{sentence_block(8)}\n```\n", "a.md") == []
    text = "See e.g. a.md v1.2.3 and https://x.io/a. Done.\n"
    assert only(audit(text, "a.md"), Rule.UNIT) == []
    findings = audit("- item\r\nlazy\r\n", "p/a.md")
    assert findings == [
        Finding(
            "p/a.md",
            2,
            Rule.LAYOUT,
            Severity.WARN,
            "(lazy continuation; indent it under its item)",
        )
    ]
    assert findings[0].rule.value == "layout"
    assert findings[0].severity.value == "warn"


def test_expand_skill_md_then_sorted_references(tmp_path: Path) -> None:
    (tmp_path / "references/sub").mkdir(parents=True)
    for relative in (
        "SKILL.md",
        "references/b.md",
        "references/a.md",
        "references/sub/c.md",
        "references/x.txt",
    ):
        (tmp_path / relative).write_text("")
    assert expand_skill_dir(tmp_path) == [
        tmp_path / "SKILL.md",
        tmp_path / "references/a.md",
        tmp_path / "references/b.md",
        tmp_path / "references/sub/c.md",
    ]


def test_how_steps_flags_numbered_and_imperative_runs() -> None:
    numbered = "1. one\n2. two\n3. three\n"
    assert only(audit(numbered, "a.md"), Rule.HOW_STEPS) == [
        (1, Severity.WARN, "(3 step-like items); outcome or how topic?")
    ]
    imperative = "# T\n- Run it\n- **Check** it\n- Write: x\n"
    assert [f[0] for f in only(audit(imperative, "a.md"), Rule.HOW_STEPS)] == [2]


def test_how_steps_ignores_short_mixed_nested_fenced_and_how_files() -> None:
    assert only(audit("1. one\n2. two\n", "a.md"), Rule.HOW_STEPS) == []
    assert (
        only(
            audit("- Run it\n- Sky is blue\n- Run it\n- Run it\n", "a.md"),
            Rule.HOW_STEPS,
        )
        == []
    )
    nested = "- Run a\n  - Run b\n  - Run c\n  - Run d\n- Run e\n"
    assert only(audit(nested, "a.md"), Rule.HOW_STEPS) == []
    fenced = "```\n1. a\n2. b\n3. c\n```\n"
    assert only(audit(fenced, "a.md"), Rule.HOW_STEPS) == []
    assert (
        only(audit("1. a\n2. b\n3. c\n", "pkg/how/skill/step.md"), Rule.HOW_STEPS) == []
    )
    assert only(audit("1. a\n2. b\n3. c\n", "s/evals/f.md"), Rule.HOW_STEPS) == []
    outdent = "  1. a\n  2. b\n  3. c\n- d\n"
    assert only(audit(outdent, "a.md"), Rule.HOW_STEPS) == [
        (1, Severity.WARN, "(3 step-like items); outcome or how topic?")
    ]


def test_how_steps_reports_line_after_frontmatter_and_splits_runs() -> None:
    text = "---\nname: x\n---\nIntro.\n1. a\n2. b\n3. c\n\nProse.\n"
    text += "- Run a\n- Run b\n- Run c\n"
    assert [f[0] for f in only(audit(text, "a.md"), Rule.HOW_STEPS)] == [5, 10]


KNOWN = frozenset(
    {"varde-a", "varde-b", "varde-orchestrate", "varde-swarm", "varde-c-d"}
)


def refs(text: str, path: str = "s/SKILL.md") -> list[tuple[int, str]]:
    return [(f.line, f.message) for f in skill_refs(text, path, "varde-a", KNOWN)]


def test_skill_refs_flags_other_skill_in_body_and_description() -> None:
    head = '---\nname: varde-a\ndescription: "Do x. Not for y (varde-b)."\n---\n'
    text = f"{head}Load varde-c-d.\n"
    assert refs(text) == [
        (3, "(names skill varde-b; say what this skill does)"),
        (5, "(names skill varde-c-d; say what this skill does)"),
    ]
    assert all(
        f.rule is Rule.SKILL_REFS for f in skill_refs(text, "x", "varde-a", KNOWN)
    )


def test_skill_refs_allows_own_orchestrating_unknown_and_prefix_names() -> None:
    assert refs("`varde learn how varde-a review`\n") == []
    assert refs("See varde-orchestrate and varde-swarm.\n") == []
    assert refs("Agent varde-builder and varde-b-extra.\n") == []
    assert refs("xvarde-b and not-varde-b\n") == []


def test_skill_refs_skips_metadata_fences_and_how_files() -> None:
    meta = (
        "---\nname: varde-a\nrequires: [varde-b]\nrecommends: [varde-c-d]\n---\nBody.\n"
    )
    assert refs(meta) == []
    assert refs("```\nvarde-b\n```\n") == []
    assert refs("varde-b\n", "pkg/how/varde-a/step.md") == []
    assert refs("varde-b\n", "s/evals/f.md") == []


def spec_messages(meta: object, directory: str = "demo", lines: int = 10) -> list[str]:
    return [f.message for f in skill_spec(meta, directory, "demo/SKILL.md", lines)]


def test_skill_spec_accepts_valid_frontmatter() -> None:
    assert spec_messages({"name": "demo", "description": "x" * 1024}) == []


def test_skill_spec_name_rules() -> None:
    for name in ("Demo", "-demo", "demo-", "de--mo", "x" * 65):
        assert len(spec_messages({"name": name, "description": "d"}, name)) == 1
    mismatch = spec_messages({"name": "demo", "description": "d"}, "other")
    assert "must match its directory" in mismatch[0]


def test_skill_spec_description_compatibility_and_size() -> None:
    assert len(spec_messages({"name": "demo", "description": "x" * 1025})) == 1
    assert len(spec_messages({"name": "demo", "description": " "})) == 1
    assert (
        len(spec_messages({"name": "demo", "description": "d", "compatibility": ""}))
        == 1
    )
    long = skill_spec({"name": "demo", "description": "d"}, "demo", "p", 501)
    assert [f.severity for f in long] == [Severity.WARN]
    assert skill_spec(None, "demo", "p", 1)[0].severity is Severity.ERROR


def eval_lines(*assertions: str) -> list[int]:
    text = json.dumps({"evals": [{"id": 1, "assertions": list(assertions)}]}, indent=1)
    findings = eval_content(text, "e.json")
    assert all(f.rule is Rule.EVAL_CONTENT for f in findings)
    assert all(f.severity is Severity.WARN for f in findings)
    return [f.line for f in findings]


def test_eval_content_flags_content_and_routing_assertions() -> None:
    flagged = (
        "Cites references/sync.md",
        "Names varde-customize as the owner",
        "Routes the request to references/a.md",
        "Reads build-execution.md directly",
        "Loads the skill and follows it",
        "Describes review once",
        "Lists the sections of the skill",
        "Does not load or follow varde-x",
        "Knows the debug rule",
    )
    assert eval_lines(*flagged) == [6 + i for i in range(len(flagged))]


def test_eval_content_allows_behavior_and_artifact_assertions() -> None:
    assert not eval_lines(
        "Runs the dry run before applying sync",
        "HTML contains Options and Tradeoffs sections",
        "Lists 2026-09-02-beta-draft as a draft to resume",
        "Names the missing capability",
        "Creates deploy-release/SKILL.md and front-loads the trigger word",
        "Routes the known declaration to `get_symbol`",
        "Reads README.md before editing",
        "Imports the varde-core package",
    )


def test_eval_content_reports_each_duplicate_assertion_line() -> None:
    assert eval_lines("Cites a.md", "Runs x", "Cites a.md") == [6, 8]


def test_eval_content_ignores_non_assertion_json() -> None:
    assert eval_content("not json", "e.json") == []
    assert eval_content('["Cites references/a.md"]', "e.json") == []
    assert eval_content('{"evals": [{"assertions": [3]}, 4]}', "e.json") == []


def sentence_findings(text: str) -> list[tuple[int, Severity, str]]:
    return only(audit(text, "a.md"), Rule.SENTENCE)


def test_sentence_threshold() -> None:
    assert sentence_findings(f"{words(25)}.\n") == []
    assert sentence_findings(f"{words(26)}.\n") == [
        (1, Severity.WARN, "(sentence, 26 words)")
    ]


def test_sentence_splits_on_terminators_and_counts_longest() -> None:
    assert sentence_findings(f"{words(20)}. {words(20)}. {words(20)}.\n") == []


def test_sentence_code_span_link_and_filename_count_as_one_word() -> None:
    span = "`" + " ".join(["a"] * 30) + "`"
    link = "[" + "text" + "](https://example.com/" + "x" * 50 + ")"
    assert sentence_findings(f"{words(22)} {span} {link} file.py.\n") == []


def test_sentence_list_item_and_line_number() -> None:
    assert sentence_findings(f"# T\n\n- {words(26)}.\n") == [
        (3, Severity.WARN, "(sentence, 26 words)")
    ]


def test_sentence_skips_fence_and_frontmatter() -> None:
    fenced = f"---\ndescription: {words(30)}\n---\n```\n{words(30)}.\n```\n"
    assert sentence_findings(fenced) == []


def test_sentence_abbreviation_and_version_do_not_split() -> None:
    text = f"{words(12)} e.g. {words(6)} v1.2 {words(6)}.\n"
    assert sentence_findings(text) == [(1, Severity.WARN, "(sentence, 26 words)")]


def test_sentence_nested_items_are_measured_separately() -> None:
    nested = "".join(f"  - {words(10)}\n" for _ in range(5))
    assert sentence_findings(f"- {words(10)}:\n{nested}") == []
    long_item = f"- {words(10)}:\n  - {words(26)}.\n"
    assert sentence_findings(long_item) == [(1, Severity.WARN, "(sentence, 26 words)")]
