//! Chunk-strategy regression tests over real captured outputs in `tests/fixtures/`.
//!
//! Each fixture is a genuine tool output (a failing `cargo test`, a `git diff` from this repo,
//! `cargo metadata`, a crate README, macOS launchd/kernel log lines). The snapshot records which
//! strategy was chosen and the resulting section titles + line ranges, so a change to the
//! sniffers or splitters shows up as a reviewable diff. Update with `cargo insta accept`.

use toz_core::capture::expand_minified_json;
use toz_core::chunk::chunk_default;
use toz_core::strategies::{detect, Strategy};

fn outline(text: &str) -> String {
    let strategy = detect(text);
    let chunks = chunk_default(text);
    // Invariants every strategy must keep: contiguous, covering, bodies are exact line slices.
    let lines: Vec<&str> = text.lines().collect();
    assert_eq!(chunks.first().map(|c| c.line_start), Some(1));
    assert_eq!(chunks.last().map(|c| c.line_end), Some(lines.len()));
    for w in chunks.windows(2) {
        assert!(
            w[1].line_start <= w[0].line_end + 1,
            "gap between chunks {} and {}",
            w[0].ordinal,
            w[1].ordinal
        );
    }
    for c in &chunks {
        assert_eq!(c.body, lines[c.line_start - 1..c.line_end].join("\n"));
    }
    let mut out = format!("strategy: {strategy:?}\nchunks: {}\n", chunks.len());
    for c in &chunks {
        out.push_str(&format!(
            "{:>3}  L{}-L{}  {:<5}  {}\n",
            c.ordinal,
            c.line_start,
            c.line_end,
            c.content_type.as_str(),
            c.title
        ));
    }
    out
}

macro_rules! fixture {
    ($name:ident, $file:literal, $strategy:expr) => {
        #[test]
        fn $name() {
            let text = include_str!(concat!("fixtures/", $file));
            assert_eq!(detect(text), $strategy, "strategy for {}", $file);
            insta::assert_snapshot!(outline(text));
        }
    };
}

fixture!(
    cargo_test_failures,
    "cargo-test-failures.txt",
    Strategy::Test
);
fixture!(git_diff, "git-diff.patch", Strategy::Diff);
fixture!(markdown_readme, "htmd-readme.md", Strategy::Markdown);
fixture!(macos_syslog, "macos-syslog.log", Strategy::Log);

#[test]
fn cargo_metadata_minified_json() {
    let raw = include_str!("fixtures/cargo-metadata.json");
    assert_eq!(raw.lines().count(), 1, "fixture should be single-line JSON");
    let text = expand_minified_json(raw.to_string());
    assert_eq!(detect(&text), Strategy::Json);
    insta::assert_snapshot!(outline(&text));
}
