//! `varde doc flow` reproduces `skill-flow.py` over a frozen corpus.
//!
//! `fixtures/flow/corpus.txt` bundles skill trees as sections headed
//! `=== <relative path> ===`: `varde-change` and `varde-docs` copied from base
//! commit `b768588d` (only what the analysis reads: `SKILL.md`, `references/`,
//! `scripts/`, `assets/`, the `skills/shared` files listed for them in
//! `MANIFEST`, and the `agents/*/claude.md` definitions), plus the synthetic
//! `varde-flow-gaps`, which adds the findings the real skills lack (missing,
//! unreferenced, cycle). The test unpacks it into a temp dir.
//!
//! The `expected-*` files are the base script's output over that tree, for
//! `varde-change varde-docs varde-flow-gaps` in that order. `expected.json`
//! also includes the Rust-only `dispatches[].files` extension. The FLOW.md
//! expectation has one section per skill (`=== <skill>/FLOW.md ===`) and one
//! deliberate change: the header line "with skill-flow.py --write from
//! varde-agent-doc-authoring. Dotted edges" reads "with `varde doc flow
//! --write`. Dotted edges". To regenerate (only if the corpus changes), unpack
//! the corpus, then from its `skills/` directory:
//!
//! ```sh
//! git show b768588d:skills/varde-agent-doc-authoring/scripts/skill-flow.py > "$TMPDIR/skill-flow.py"
//! S="varde-change varde-docs varde-flow-gaps"
//! python3 "$TMPDIR/skill-flow.py" $S > expected-text.txt
//! python3 "$TMPDIR/skill-flow.py" --mermaid $S > expected-mermaid.txt
//! python3 "$TMPDIR/skill-flow.py" --json $S > expected.json
//! python3 "$TMPDIR/skill-flow.py" --write $S   # then bundle each FLOW.md and fix the header
//! ```
//!
//! Preserve the Rust `dispatches[].files` values when regenerating `expected.json`.
//! `--json` compares by value: Python escapes non-ASCII text, serde_json does not.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use varde_doc::flow::{Analysis, analyze, flow_doc, mermaid, text_report};

const SKILLS: [&str; 3] = ["varde-change", "varde-docs", "varde-flow-gaps"];

/// Split `=== <name> ===` sections into (name, body) pairs.
fn sections(text: &str) -> Vec<(&str, &str)> {
    let mut found = Vec::new();
    let mut rest = text;
    while let Some(after) = rest.strip_prefix("=== ") {
        let (name, body) = after.split_once(" ===\n").expect("section header");
        let end = body.find("\n=== ").map_or(body.len(), |at| at + 1);
        found.push((name, &body[..end]));
        rest = &body[end..];
    }
    assert!(rest.is_empty(), "unparsed corpus text");
    found
}

fn unpack(root: &Path) {
    for (name, body) in sections(include_str!("fixtures/flow/corpus.txt")) {
        let path = root.join(name);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, body).unwrap();
    }
}

fn analyses() -> (tempfile::TempDir, Vec<Analysis>) {
    let tmp = tempfile::tempdir().unwrap();
    unpack(tmp.path());
    let skills = SKILLS
        .iter()
        .map(|name| analyze(&tmp.path().join("skills").join(name)).expect("analyze"))
        .collect();
    (tmp, skills)
}

/// What the CLI prints: reports joined by a blank line, plus a final newline.
fn printed(reports: Vec<String>) -> String {
    reports.join("\n\n") + "\n"
}

#[test]
fn text_matches_the_script() {
    let (_tmp, skills) = analyses();
    let actual = printed(skills.iter().map(text_report).collect());
    assert_eq!(actual, include_str!("fixtures/flow/expected-text.txt"));
}

#[test]
fn mermaid_matches_the_script() {
    let (_tmp, skills) = analyses();
    let actual = printed(skills.iter().map(mermaid).collect());
    assert_eq!(actual, include_str!("fixtures/flow/expected-mermaid.txt"));
}

#[test]
fn json_matches_the_script_by_value() {
    let (_tmp, skills) = analyses();
    let actual = serde_json::to_value(&skills).unwrap();
    let expected: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/flow/expected.json")).unwrap();
    // The fixture also pins the Rust-only Dispatch.files extension.
    assert_eq!(actual, expected);
}

#[test]
fn flow_doc_matches_the_script_except_the_header() {
    let (_tmp, skills) = analyses();
    let actual: BTreeMap<String, String> = skills
        .iter()
        .zip(SKILLS)
        .map(|(skill, name)| (format!("{name}/FLOW.md"), flow_doc(skill)))
        .collect();
    let expected: BTreeMap<String, String> =
        sections(include_str!("fixtures/flow/expected-FLOW.md"))
            .into_iter()
            .map(|(name, body)| (name.to_string(), body.to_string()))
            .collect();
    assert_eq!(actual, expected);
}

#[test]
fn the_corpus_exercises_every_finding_kind() {
    let (_tmp, skills) = analyses();
    let seen = |count: fn(&Analysis) -> usize| skills.iter().any(|s| count(s) > 0);
    assert!(seen(|s| s.findings.chain.len()));
    assert!(seen(|s| s.findings.single_caller.len()));
    assert!(seen(|s| s.findings.shared.len()));
    assert!(seen(|s| s.findings.unreferenced.len()));
    assert!(seen(|s| s.findings.missing.len()));
    assert!(seen(|s| s.findings.cycle.len()));
    assert!(seen(|s| s.findings.fan_out.len()));
    assert!(seen(|s| s.findings.density.len()));
}
