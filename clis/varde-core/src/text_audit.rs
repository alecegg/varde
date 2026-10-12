//! Length and layout audit for agent documents (port of `check-length.py`).
//!
//! Units are prose blocks and top-level list items with everything nested
//! under them. Rules: `unit` (sentences), `section` (words), `prose-share`
//! (percent of words in prose blocks), `inline-list` and `layout`.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use regex::{Captures, Regex};
use serde::Serialize;

const UNIT_WARN: usize = 4;
const UNIT_ERROR: usize = 6;
const SECTION_WARN: usize = 250;
const SECTION_ERROR: usize = 400;
const PROSE_WARN: usize = 40;
const PROSE_ERROR: usize = 60;
const PROSE_MIN_WORDS: usize = 150;

const HINT_PROSE: &str = "; steps or lists written as sentences?";
const HINT_SERIES: &str = "; put one item per line under a lead-in";

/// How serious a finding is.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Severity {
    Warn,
    Error,
}

/// Which audit rule produced a finding.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum Rule {
    Unit,
    Section,
    ProseShare,
    InlineList,
    Layout,
}

/// One audit finding.
///
/// `message` is the exact text `check-length.py` prints after `path:line `,
/// for example `(unit, 5 sentences)` or `(inline list, 4 items); put one ...`.
/// A text renderer prints `{ERROR|WARN } {path}:{line} {message}`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Finding {
    pub path: String,
    pub line: usize,
    pub rule: Rule,
    pub severity: Severity,
    pub message: String,
}

fn re(pattern: &str) -> Regex {
    Regex::new(pattern).expect("static pattern is valid")
}

static ITEM: LazyLock<Regex> = LazyLock::new(|| re(r"^(\s*)([-*+]|\d+[.)])\s+"));
static INLINE_CODE: LazyLock<Regex> = LazyLock::new(|| re(r"`[^`]*`"));
static STRIP: LazyLock<Vec<Regex>> = LazyLock::new(|| {
    vec![
        re(r"`[^`]*`"),
        re(r"\[([^\]]*)\]\([^)]*\)"),
        re(r"https?://\S+"),
        re(r"(?i)\b(e\.g|i\.e|etc|vs|cf|approx)\."),
        re(r"\bv?\d+(\.\d+)+\b"),
        re(r"[\w./-]+\.[A-Za-z]{1,5}\b"),
    ]
});
static SENTENCE_END: LazyLock<Regex> = LazyLock::new(|| re(r#"[.!?][)"'*_]*(\s|$)"#));
static SERIES: LazyLock<Regex> =
    LazyLock::new(|| re(r"(?:[^,;:.!?()]+,\s*){2,}[^,;:.!?()]*?\b(?:and|or)\b[^,;:.!?()]*"));
static LEAD_CONJUNCTION: LazyLock<Regex> = LazyLock::new(|| re(r"^\s*(and|or)\s+"));

/// Python `str.isspace` also counts the ASCII separators 0x1c-0x1f.
fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\x1c'..='\x1f').contains(&c)
}

fn strip(s: &str) -> &str {
    s.trim_matches(is_space)
}

fn word_count(s: &str) -> usize {
    s.split(is_space).filter(|w| !w.is_empty()).count()
}

fn sentences(text: &str) -> usize {
    let mut text = text.to_string();
    for pattern in STRIP.iter() {
        // Patterns with a group keep it; the rest become "x".
        text = pattern
            .replace_all(&text, |caps: &Captures| {
                caps.get(1).map_or("x", |m| m.as_str()).to_string()
            })
            .into_owned();
    }
    SENTENCE_END.find_iter(&text).count()
}

/// Four or more items, or three when a later item runs three or more words.
fn is_list_worthy(series: &str) -> bool {
    let items: Vec<usize> = series
        .split(',')
        .map(|part| word_count(&LEAD_CONJUNCTION.replace(part, "")))
        .collect();
    items.len() >= 4 || items[1..].iter().copied().max().unwrap_or(0) >= 3
}

/// Index of the first body line; 0 when there is no frontmatter.
fn frontmatter_end(lines: &[&str]) -> usize {
    if lines.first().is_none_or(|l| strip(l) != "---") {
        return 0;
    }
    lines
        .iter()
        .enumerate()
        .skip(1)
        .find(|(_, l)| strip(l) == "---")
        .map_or(0, |(n, _)| n + 1)
}

fn is_fence(stripped: &str) -> bool {
    stripped.starts_with("```") || stripped.starts_with("~~~")
}

fn indent_of(line: &str) -> usize {
    line.chars().take_while(|&c| is_space(c)).count()
}

fn item_end(line: &str) -> Option<usize> {
    ITEM.find(line).map(|m| m.end())
}

/// Python reads files with universal newlines.
fn normalize(text: &str) -> String {
    text.replace("\r\n", "\n").replace('\r', "\n")
}

#[derive(Default)]
struct Scanner {
    path: String,
    findings: Vec<Finding>,
    unit: Vec<String>,
    unit_line: usize,
    in_item: bool,
    item_indent: usize,
}

impl Scanner {
    fn push(&mut self, rule: Rule, line: usize, size: usize) {
        let (warn_at, error_at, measure, label, hint) = match rule {
            Rule::Unit => (UNIT_WARN, UNIT_ERROR, "sentences", "unit", ""),
            Rule::InlineList => (0, usize::MAX, "items", "inline list", HINT_SERIES),
            Rule::Section => (SECTION_WARN + 1, SECTION_ERROR + 1, "words", "section", ""),
            Rule::ProseShare | Rule::Layout => (
                PROSE_WARN + 1,
                PROSE_ERROR + 1,
                "percent",
                "prose share",
                HINT_PROSE,
            ),
        };
        let severity = if size >= error_at {
            Severity::Error
        } else if size >= warn_at {
            Severity::Warn
        } else {
            return;
        };
        self.findings.push(Finding {
            path: self.path.clone(),
            line,
            rule,
            severity,
            message: format!("({label}, {size} {measure}){hint}"),
        });
    }

    fn close_unit(&mut self) {
        if !self.unit.is_empty() {
            let text = self.unit.join(" ");
            let line = self.unit_line;
            self.push(Rule::Unit, line, sentences(&text));
            let plain = INLINE_CODE.replace_all(&text, "x");
            let found = SERIES
                .find_iter(&plain)
                .map(|m| m.as_str())
                .find(|s| is_list_worthy(s))
                .map(|s| s.matches(',').count() + 1);
            if let Some(size) = found {
                self.push(Rule::InlineList, line, size);
            }
        }
        self.unit.clear();
        self.in_item = false;
        self.item_indent = 0;
    }
}

fn scan(path: &str, lines: &[&str]) -> Vec<Finding> {
    let first = frontmatter_end(lines);
    let mut s = Scanner {
        path: path.to_string(),
        ..Scanner::default()
    };
    let mut fenced = false;
    let (mut section_words, mut section_line) = (0, first + 1);
    let (mut prose_words, mut total_words) = (0, 0);

    for (n, line) in (first + 1..).zip(&lines[first..]) {
        let stripped = strip(line);
        let indent = indent_of(line);
        let inside_item = s.in_item && indent > s.item_indent;
        if is_fence(stripped) {
            fenced = !fenced;
            if !inside_item {
                s.close_unit();
            }
            continue;
        }
        if fenced || stripped.is_empty() {
            continue; // blank lines never end a unit; only structure does
        }
        let words = word_count(stripped);
        total_words += words;
        if stripped.starts_with('#') {
            s.close_unit();
            s.push(Rule::Section, section_line, section_words);
            section_words = 0;
            section_line = n;
            continue;
        }
        if stripped.starts_with('|') || stripped.starts_with("<!--") {
            if !inside_item {
                s.close_unit();
            }
            continue;
        }
        section_words += words;
        let item = item_end(line);
        if inside_item {
            // A nested item is its own clause, so it never joins a series.
            s.unit.push(match item {
                Some(end) => format!("; {}", &line[end..]),
                None => stripped.to_string(),
            });
        } else if let Some(end) = item {
            s.close_unit();
            s.unit.push(line[end..].to_string());
            s.unit_line = n;
            s.in_item = true;
            s.item_indent = indent;
        } else if !s.unit.is_empty() && !s.in_item {
            s.unit.push(stripped.to_string());
            prose_words += words;
        } else {
            s.close_unit();
            s.unit
                .push(stripped.trim_start_matches(['>', ' ']).to_string());
            s.unit_line = n;
            prose_words += words;
        }
    }
    s.close_unit();
    s.push(Rule::Section, section_line, section_words);
    if total_words >= PROSE_MIN_WORDS {
        s.push(Rule::ProseShare, first + 1, 100 * prose_words / total_words);
    }
    s.findings
}

fn layout(path: &str, lines: &[&str]) -> Vec<Finding> {
    let mut out = Vec::new();
    let first = frontmatter_end(lines);
    let (mut fenced, mut previous_item) = (false, false);
    let mut note = |n: usize, text: &str| {
        out.push(Finding {
            path: path.to_string(),
            line: n,
            rule: Rule::Layout,
            severity: Severity::Warn,
            message: format!("({text})"),
        });
    };
    for (n, line) in (first + 1..).zip(&lines[first..]) {
        let stripped = strip(line);
        if is_fence(stripped) {
            fenced = !fenced;
            previous_item = false;
            continue;
        }
        if fenced
            || stripped.is_empty()
            || ["#", "|", "<!--", "---"]
                .iter()
                .any(|p| stripped.starts_with(p))
        {
            previous_item = false;
            continue;
        }
        if stripped == "</content>" {
            note(n, "stray </content> line");
        }
        let item = item_end(line).is_some();
        let indented = line.starts_with(is_space);
        if previous_item && !item && !indented {
            note(n, "lazy continuation; indent it under its item");
        }
        previous_item = item || (previous_item && indented);
    }
    out
}

/// Audit Markdown `text`, labelling findings with `path`.
///
/// Scan findings (unit, inline-list, section, prose-share) come first in
/// script order, then layout findings.
pub fn audit(text: &str, path: &str) -> Vec<Finding> {
    let text = normalize(text);
    let lines: Vec<&str> = text.split('\n').collect();
    let mut findings = scan(path, &lines);
    findings.extend(layout(path, &lines));
    findings
}

/// Markdown files of a skill directory: `SKILL.md`, then `references/**/*.md`
/// sorted by path. Lists paths only; it reads no file contents.
pub fn expand_skill_dir(dir: &Path) -> Vec<PathBuf> {
    let mut found = Vec::new();
    if dir.join("SKILL.md").is_file() {
        found.push(dir.join("SKILL.md"));
    }
    let mut refs = Vec::new();
    collect_markdown(&dir.join("references"), &mut refs);
    refs.sort();
    found.extend(refs);
    found
}

fn collect_markdown(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if entry.file_type().is_ok_and(|t| t.is_dir()) {
            collect_markdown(&path, out);
        } else if path.extension().is_some_and(|e| e == "md") {
            out.push(path);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn words(n: usize) -> String {
        vec!["word"; n].join(" ")
    }

    fn sentence_block(n: usize) -> String {
        vec!["Short one."; n].join(" ")
    }

    fn only(findings: &[Finding], rule: Rule) -> Vec<(usize, Severity, String)> {
        findings
            .iter()
            .filter(|f| f.rule == rule)
            .map(|f| (f.line, f.severity, f.message.clone()))
            .collect()
    }

    #[test]
    fn unit_warns_at_four_and_errors_at_six_sentences() {
        let f = audit(&sentence_block(3), "a.md");
        assert!(only(&f, Rule::Unit).is_empty());
        let f = audit(&sentence_block(4), "a.md");
        assert_eq!(
            only(&f, Rule::Unit),
            [(1, Severity::Warn, "(unit, 4 sentences)".into())]
        );
        let f = audit(&sentence_block(6), "a.md");
        assert_eq!(
            only(&f, Rule::Unit),
            [(1, Severity::Error, "(unit, 6 sentences)".into())]
        );
    }

    #[test]
    fn list_item_with_nested_content_is_one_unit() {
        let text = format!("- {}\n  - {}\n", sentence_block(2), sentence_block(2));
        let f = audit(&text, "a.md");
        assert_eq!(
            only(&f, Rule::Unit),
            [(1, Severity::Warn, "(unit, 4 sentences)".into())]
        );
    }

    #[test]
    fn section_warns_over_250_and_errors_over_400_words() {
        let f = audit(&format!("# T\n{}\n", words(250)), "a.md");
        assert!(only(&f, Rule::Section).is_empty());
        let f = audit(&format!("# T\n{}\n", words(251)), "a.md");
        assert_eq!(
            only(&f, Rule::Section),
            [(1, Severity::Warn, "(section, 251 words)".into())]
        );
        let f = audit(&format!("# T\n{}\n", words(401)), "a.md");
        assert_eq!(
            only(&f, Rule::Section),
            [(1, Severity::Error, "(section, 401 words)".into())]
        );
    }

    #[test]
    fn section_line_points_after_frontmatter() {
        let f = audit(&format!("---\nname: x\n---\n# T\n{}\n", words(251)), "a.md");
        assert_eq!(only(&f, Rule::Section)[0].0, 4);
    }

    // `other` is the word count of the list part; each "- word" item has two words.
    fn prose_doc(prose: usize, other: usize) -> String {
        let list: Vec<String> = (0..other / 2).map(|_| "- word".to_string()).collect();
        format!("{}\n\n{}\n", words(prose), list.join("\n"))
    }

    #[test]
    fn prose_share_warns_over_40_and_errors_over_60_percent() {
        let hint = "; steps or lists written as sentences?";
        // 150 total words: 60 prose = 40% (no finding), 62 = 41% (warn), 92 = 61% (error).
        let f = audit(&prose_doc(60, 90), "a.md");
        assert!(only(&f, Rule::ProseShare).is_empty());
        let f = audit(&prose_doc(62, 88), "a.md");
        assert_eq!(
            only(&f, Rule::ProseShare),
            [(
                1,
                Severity::Warn,
                format!("(prose share, 41 percent){hint}")
            )]
        );
        let f = audit(&prose_doc(92, 58), "a.md");
        assert_eq!(
            only(&f, Rule::ProseShare),
            [(
                1,
                Severity::Error,
                format!("(prose share, 61 percent){hint}")
            )]
        );
        // Under 150 words the rule is skipped.
        assert!(only(&audit(&words(100), "a.md"), Rule::ProseShare).is_empty());
    }

    #[test]
    fn inline_list_is_warn_only() {
        // The rule has no error level (the script's error threshold is unreachable).
        let hint = "; put one item per line under a lead-in";
        let f = audit("Use red, green, blue, and gold.\n", "a.md");
        assert_eq!(
            only(&f, Rule::InlineList),
            [(1, Severity::Warn, format!("(inline list, 4 items){hint}"))]
        );
        let f = audit("Use red, green, and blue.\n", "a.md");
        assert!(only(&f, Rule::InlineList).is_empty());
        let f = audit("Use red, green, and a deep blue sea.\n", "a.md");
        assert_eq!(
            only(&f, Rule::InlineList),
            [(1, Severity::Warn, format!("(inline list, 3 items){hint}"))]
        );
    }

    #[test]
    fn layout_is_warn_only() {
        let f = audit("- item\nlazy\n", "a.md");
        assert_eq!(
            only(&f, Rule::Layout),
            [(
                2,
                Severity::Warn,
                "(lazy continuation; indent it under its item)".into()
            )]
        );
        let f = audit("text\n</content>\n", "a.md");
        assert_eq!(
            only(&f, Rule::Layout),
            [(2, Severity::Warn, "(stray </content> line)".into())]
        );
        assert!(only(&audit("- item\n  fine\n", "a.md"), Rule::Layout).is_empty());
    }

    #[test]
    fn code_fences_and_strip_patterns_are_ignored() {
        let text = format!("```\n{}\n```\n", sentence_block(8));
        assert!(audit(&text, "a.md").is_empty());
        let text = "See e.g. a.md v1.2.3 and https://x.io/a. Done.\n";
        assert!(only(&audit(text, "a.md"), Rule::Unit).is_empty());
    }

    #[test]
    fn crlf_is_normalized_and_findings_serialize() {
        let f = audit("- item\r\nlazy\r\n", "p/a.md");
        assert_eq!(f.len(), 1);
        let v = serde_json::to_value(&f[0]).unwrap();
        assert_eq!(v["path"], "p/a.md");
        assert_eq!(v["rule"], "layout");
        assert_eq!(v["severity"], "warn");
    }

    #[test]
    fn expand_lists_skill_md_then_sorted_references() {
        let dir = std::env::temp_dir().join(format!("text-audit-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(dir.join("references/sub")).unwrap();
        let files = [
            "SKILL.md",
            "references/b.md",
            "references/a.md",
            "references/sub/c.md",
            "references/x.txt",
        ];
        for p in files {
            fs::write(dir.join(p), "").unwrap();
        }
        let got = expand_skill_dir(&dir);
        let want: Vec<PathBuf> = [
            "SKILL.md",
            "references/a.md",
            "references/b.md",
            "references/sub/c.md",
        ]
        .iter()
        .map(|p| dir.join(p))
        .collect();
        fs::remove_dir_all(&dir).unwrap();
        assert_eq!(got, want);
    }
}
