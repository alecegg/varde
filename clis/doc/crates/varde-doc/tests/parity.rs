//! `varde doc lint` reproduces `check-length.py` over a frozen corpus.
//!
//! `fixtures/corpus/` holds Markdown copied from base commit `b768588d`, and
//! `fixtures/corpus-expected.txt` is the base script's output over it. Neither
//! tracks later skill edits. To regenerate the expectation (only if the corpus
//! or the list below changes), from `tests/fixtures`:
//!
//! ```sh
//! git show b768588d:skills/varde-agent-doc-authoring/scripts/check-length.py > "$TMPDIR/check-length.py"
//! python3 "$TMPDIR/check-length.py" corpus/<each file below, in order> > corpus-expected.txt
//! ```
//!
//! The test lints absolute paths (no `set_current_dir`) and strips the
//! fixtures directory prefix so paths print as `corpus/...`, as in the file.

use std::path::{Path, PathBuf};

/// Corpus files, relative to `fixtures/corpus/`, in the order the expected
/// output was generated.
const CORPUS: &[&str] = &[
    "agents/README.md",
    "clis/code/docs/ARCHITECTURE.md",
    "skills/varde-agent-doc-authoring/assets/flow-ledger-prompt.md",
    "skills/varde-change/SKILL.md",
    "skills/varde-change/references/build-execution.md",
    "skills/varde-change/references/orchestration.md",
    "skills/varde-change/references/plan.md",
    "skills/varde-code/FLOW.md",
    "skills/varde-review/FLOW.md",
    "skills/varde-review/SKILL.md",
];

#[test]
fn text_output_matches_check_length_over_frozen_corpus() {
    let fixtures = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures");
    let paths: Vec<PathBuf> = CORPUS
        .iter()
        .map(|file| fixtures.join("corpus").join(file))
        .collect();
    let report = varde_doc::lint(&paths).expect("lint corpus");
    let prefix = format!("{}/", fixtures.display());
    let actual = report.render_text().replace(&prefix, "");
    let expected = include_str!("fixtures/corpus-expected.txt");
    assert_eq!(actual, expected);
    // The corpus must keep exercising both severities and the exit-1 path.
    assert!(report.errors() > 0);
    assert!(report.warnings() > 0);
}
