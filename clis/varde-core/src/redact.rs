//! Shared redaction engine: built-in and user patterns, literal secret values,
//! partial reveal, and the notices that record what was replaced.
//!
//! Callers with the whole text use [`Redactor::redact`]; streaming callers that
//! write the replacements themselves use [`Redactor::redact_spans`].

pub mod values;

use regex::Regex;

/// Built-in patterns. Each is `(kind, regex)`; matches are replaced with `[redacted:<kind>]`.
const BUILTIN: &[(&str, &str)] = &[
    ("aws-key", r"AKIA[0-9A-Z]{16}"),
    (
        "aws-secret",
        r#"(?i)aws_secret_access_key\s*[=:]\s*["']?[A-Za-z0-9/+=]{40}"#,
    ),
    ("github", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b"),
    ("github-pat", r"\bgithub_pat_[A-Za-z0-9_]{80,}\b"),
    ("api-key", r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}\b"),
    ("slack", r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"),
    ("bearer", r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]{16,}=*"),
    (
        "pem",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    ),
    (
        "env-assign",
        r#"(?im)^\s*(?:export\s+)?[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|PRIVATE_KEY)[A-Z0-9_]*\s*=\s*\S+"#,
    ),
    ("url-creds", r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s@/]+@"),
];

/// Configuration for [`Redactor::new`].
#[derive(Debug, Clone)]
pub struct RedactConfig {
    /// Match the built-in pattern table.
    pub builtin: bool,
    /// Extra regex patterns; each is reported with kind `user`.
    pub patterns: Vec<String>,
    /// Literal values to redact, typically secret environment variables.
    pub values: Vec<SecretValue>,
    /// Characters kept at each end of a long value; `0` hides it fully.
    pub reveal: usize,
}

impl Default for RedactConfig {
    fn default() -> Self {
        Self {
            builtin: true,
            patterns: Vec::new(),
            values: Vec::new(),
            reveal: 2,
        }
    }
}

/// A secret value to match literally. `name` is a variable name, never secret.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SecretValue {
    pub name: String,
    pub value: String,
}

/// Which rule replaced a span.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Pattern,
    Value,
}

/// One replacement in the original text; `text[start..end]` becomes `replacement`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Span {
    pub start: usize,
    pub end: usize,
    pub replacement: String,
    pub kind: Kind,
}

/// Replacements made by one rule, aggregated per `(kind, label)`.
///
/// A notice never carries matched text: `label` is a pattern kind or a variable name.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Notice {
    pub kind: Kind,
    pub label: String,
    pub count: usize,
}

/// Redacted text plus the notices describing what was replaced.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Redacted {
    pub text: String,
    pub notices: Vec<Notice>,
}

/// A redaction candidate before overlapping ones are resolved.
///
/// It stores only the rule index; the replacement and label are looked up from
/// [`Redactor::rules`] once the candidate survives overlap resolution.
struct Candidate {
    start: usize,
    end: usize,
    /// Index into [`Redactor::rules`]; also the tie-break precedence.
    order: usize,
}

/// How one rule finds matches.
#[derive(Debug)]
enum Matcher {
    Regex(Regex),
    Literal(String),
}

/// One compiled rule with its replacement and notice label prepared once.
#[derive(Debug)]
struct Rule {
    matcher: Matcher,
    /// `[redacted:<kind>]`, or the value replacement with its partial reveal.
    replacement: String,
    kind: Kind,
    /// A pattern kind or the value's variable name.
    label: String,
}

/// Compiled redaction rules.
#[derive(Debug)]
pub struct Redactor {
    /// Built-ins first, then user patterns as `user`, then the literal values.
    rules: Vec<Rule>,
}

impl Redactor {
    /// Compile `cfg`. An invalid user pattern returns an error naming it.
    pub fn new(cfg: &RedactConfig) -> Result<Self, String> {
        let mut rules = Vec::new();
        if cfg.builtin {
            for (kind, pattern) in BUILTIN {
                rules.push(Rule {
                    matcher: Matcher::Regex(Regex::new(pattern).expect("builtin regex")),
                    replacement: format!("[redacted:{kind}]"),
                    kind: Kind::Pattern,
                    label: (*kind).to_string(),
                });
            }
        }
        for pattern in &cfg.patterns {
            let regex = Regex::new(pattern)
                .map_err(|err| format!("invalid redact pattern {pattern:?}: {err}"))?;
            rules.push(Rule {
                matcher: Matcher::Regex(regex),
                replacement: "[redacted:user]".to_string(),
                kind: Kind::Pattern,
                label: "user".to_string(),
            });
        }

        let mut values: Vec<&SecretValue> = cfg
            .values
            .iter()
            .filter(|value| !value.value.is_empty())
            .collect();
        values.sort_by(|a, b| {
            b.value
                .len()
                .cmp(&a.value.len())
                .then_with(|| a.name.cmp(&b.name))
        });
        for value in values {
            rules.push(Rule {
                matcher: Matcher::Literal(value.value.clone()),
                replacement: value_replacement(cfg.reveal, &value.name, &value.value),
                kind: Kind::Value,
                label: value.name.clone(),
            });
        }

        Ok(Self { rules })
    }

    /// Replace every match in `text` and report what was replaced.
    pub fn redact(&self, text: &str) -> Redacted {
        let mut out = String::with_capacity(text.len());
        let mut cursor = 0;
        let mut notices: Vec<Notice> = Vec::new();
        for candidate in self.selected(text) {
            let rule = &self.rules[candidate.order];
            out.push_str(&text[cursor..candidate.start]);
            out.push_str(&rule.replacement);
            cursor = candidate.end;
            match notices
                .iter_mut()
                .find(|notice| notice.kind == rule.kind && notice.label == rule.label)
            {
                Some(notice) => notice.count += 1,
                None => notices.push(Notice {
                    kind: rule.kind,
                    label: rule.label.clone(),
                    count: 1,
                }),
            }
        }
        out.push_str(&text[cursor..]);
        Redacted { text: out, notices }
    }

    /// Return the replacements for `text` as sorted, non-overlapping spans.
    pub fn redact_spans(&self, text: &str) -> Vec<Span> {
        self.selected(text)
            .into_iter()
            .map(|candidate| {
                let rule = &self.rules[candidate.order];
                Span {
                    start: candidate.start,
                    end: candidate.end,
                    replacement: rule.replacement.clone(),
                    kind: rule.kind,
                }
            })
            .collect()
    }

    /// Every candidate match, sorted by earliest start, then longest, then rule.
    ///
    /// Only the range and rule index are recorded; the replacement and label are
    /// looked up for the candidates that survive [`Self::selected`].
    fn candidates(&self, text: &str) -> Vec<Candidate> {
        let mut candidates = Vec::new();
        for (order, rule) in self.rules.iter().enumerate() {
            match &rule.matcher {
                Matcher::Regex(regex) => {
                    for matched in regex.find_iter(text) {
                        candidates.push(Candidate {
                            start: matched.start(),
                            end: matched.end(),
                            order,
                        });
                    }
                }
                Matcher::Literal(value) => {
                    for (start, _) in text.match_indices(value.as_str()) {
                        candidates.push(Candidate {
                            start,
                            end: start + value.len(),
                            order,
                        });
                    }
                }
            }
        }
        candidates.sort_by(|a, b| {
            a.start
                .cmp(&b.start)
                .then_with(|| b.end.cmp(&a.end))
                .then_with(|| a.order.cmp(&b.order))
        });
        candidates
    }

    /// Greedily keep candidates by earliest start, then longest.
    ///
    /// A candidate that starts inside the last kept span but ends after it extends
    /// that span, so no matched byte is ever emitted; the kept replacement and
    /// notice stay those of the earlier candidate.
    fn selected(&self, text: &str) -> Vec<Candidate> {
        let mut selected: Vec<Candidate> = Vec::new();
        let mut last_end = 0;
        let mut last_empty: Option<usize> = None;
        for candidate in self.candidates(text) {
            if candidate.start < last_end {
                if let Some(last) = selected.last_mut() {
                    if candidate.end > last.end {
                        last.end = candidate.end;
                        last_end = candidate.end;
                    }
                }
                continue;
            }
            if candidate.start == candidate.end && last_empty == Some(candidate.start) {
                continue;
            }
            last_empty = (candidate.start == candidate.end).then_some(candidate.start);
            last_end = candidate.end;
            selected.push(candidate);
        }
        selected
    }
}

/// The replacement for one value: fully hidden, or with `reveal` characters kept.
fn value_replacement(reveal: usize, name: &str, value: &str) -> String {
    let marker = format!("[redacted:value:{name}]");
    let chars: Vec<char> = value.chars().collect();
    if reveal == 0 || chars.len() < 4 * reveal + 8 {
        return marker;
    }
    let head: String = chars[..reveal].iter().collect();
    let tail: String = chars[chars.len() - reveal..].iter().collect();
    format!("{head}…{tail}{marker}")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sv(name: &str, value: &str) -> SecretValue {
        SecretValue {
            name: name.to_string(),
            value: value.to_string(),
        }
    }

    fn values(pairs: &[(&str, &str)]) -> Vec<SecretValue> {
        pairs.iter().map(|(name, value)| sv(name, value)).collect()
    }

    fn redactor(cfg: &RedactConfig) -> Redactor {
        Redactor::new(cfg).expect("config")
    }

    #[test]
    fn default_config_is_builtin_with_reveal_two() {
        let cfg = RedactConfig::default();
        assert!(cfg.builtin);
        assert_eq!(cfg.reveal, 2);
        assert!(cfg.patterns.is_empty());
        assert!(cfg.values.is_empty());
    }

    #[test]
    fn every_builtin_pattern_redacts_with_its_kind() {
        let cases: Vec<(&str, String, &str)> = vec![
            (
                "aws-key",
                "AKIAIOSFODNN7EXAMPLE".into(),
                "AKIAIOSFODNN7EXAMPLE",
            ),
            (
                "aws-secret",
                "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY".into(),
                "EXAMPLEKEY",
            ),
            (
                "github",
                "ghp_abcdefghijklmnopqrstuvwxyz0123456789".into(),
                "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            ),
            (
                "github-pat",
                format!("github_pat_{}", "a".repeat(82)),
                "github_pat_",
            ),
            ("api-key", format!("sk-proj-{}", "b".repeat(24)), "sk-proj-"),
            ("slack", "xoxb-1234567890".into(), "xoxb-1234567890"),
            (
                "bearer",
                "Bearer abcdefghijklmnop".into(),
                "abcdefghijklmnop",
            ),
            (
                "pem",
                "-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----".into(),
                "MIIB",
            ),
            ("env-assign", "DATABASE_PASSWORD=hunter2".into(), "hunter2"),
            (
                "url-creds",
                "https://alice:s3cr3t@example.com".into(),
                "s3cr3t",
            ),
        ];
        for (kind, secret, needle) in cases {
            let out = redactor(&RedactConfig::default()).redact(&secret);
            assert!(
                out.text.contains(&format!("[redacted:{kind}]")),
                "{kind}: {}",
                out.text
            );
            assert!(!out.text.contains(needle), "{kind}: {}", out.text);
            let notice = out
                .notices
                .iter()
                .find(|notice| notice.label == kind)
                .unwrap_or_else(|| panic!("{kind}: no notice"));
            assert_eq!(notice.kind, Kind::Pattern, "{kind}");
            assert_eq!(notice.count, 1, "{kind}");
        }
    }

    #[test]
    fn builtin_disabled_leaves_the_text_alone() {
        let token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789";
        let cfg = RedactConfig {
            builtin: false,
            ..Default::default()
        };
        let out = redactor(&cfg).redact(token);
        assert_eq!(out.text, token);
        assert!(out.notices.is_empty());
    }

    #[test]
    fn user_pattern_reports_kind_user() {
        let cfg = RedactConfig {
            builtin: false,
            patterns: vec!["secret-[0-9]+".into()],
            ..Default::default()
        };
        let out = redactor(&cfg).redact("a secret-42 b");
        assert_eq!(out.text, "a [redacted:user] b");
        assert_eq!(
            out.notices,
            vec![Notice {
                kind: Kind::Pattern,
                label: "user".into(),
                count: 1,
            }]
        );
    }

    #[test]
    fn invalid_user_pattern_names_the_pattern() {
        let cfg = RedactConfig {
            patterns: vec!["[unterminated".into()],
            ..Default::default()
        };
        let err = Redactor::new(&cfg).expect_err("invalid pattern");
        assert!(err.contains("[unterminated"), "{err}");
    }

    #[test]
    fn value_is_matched_literally_with_partial_reveal() {
        let cfg = RedactConfig {
            builtin: false,
            values: values(&[("TOKEN", "supersecretvalue")]),
            ..Default::default()
        };
        let out = redactor(&cfg).redact("token is supersecretvalue here");
        assert_eq!(out.text, "token is su…ue[redacted:value:TOKEN] here");
        assert_eq!(
            out.notices,
            vec![Notice {
                kind: Kind::Value,
                label: "TOKEN".into(),
                count: 1,
            }]
        );
    }

    #[test]
    fn reveal_boundary_hides_values_below_four_reveal_plus_eight() {
        let hidden = "x".repeat(15);
        let shown = "x".repeat(16);
        let config = |value: String| RedactConfig {
            builtin: false,
            values: vec![sv("A", &value)],
            ..Default::default()
        };
        assert_eq!(
            redactor(&config(hidden.clone())).redact(&hidden).text,
            "[redacted:value:A]"
        );
        assert_eq!(
            redactor(&config(shown.clone())).redact(&shown).text,
            "xx…xx[redacted:value:A]"
        );
    }

    #[test]
    fn reveal_zero_hides_the_whole_value() {
        let cfg = RedactConfig {
            builtin: false,
            reveal: 0,
            values: vec![sv("A", "abcdefghijklmnopqrst")],
            ..Default::default()
        };
        assert_eq!(
            redactor(&cfg).redact("abcdefghijklmnopqrst").text,
            "[redacted:value:A]"
        );
    }

    #[test]
    fn reveal_three_keeps_three_characters_per_end() {
        let cfg = RedactConfig {
            builtin: false,
            reveal: 3,
            values: vec![sv("A", "abcdefghijklmnopqrst")],
            ..Default::default()
        };
        assert_eq!(
            redactor(&cfg).redact("abcdefghijklmnopqrst").text,
            "abc…rst[redacted:value:A]"
        );
    }

    #[test]
    fn overlapping_values_resolve_to_the_longest_at_the_earliest_start() {
        let cfg = RedactConfig {
            builtin: false,
            values: values(&[("ABC", "abc"), ("ABCDEF", "abcdef")]),
            ..Default::default()
        };
        assert_eq!(
            redactor(&cfg).redact("abcdef").text,
            "[redacted:value:ABCDEF]"
        );
    }

    #[test]
    fn earliest_start_wins_and_an_overlapping_value_extends_it() {
        let cfg = RedactConfig {
            builtin: false,
            values: values(&[("LATER", "bcde"), ("EARLY", "abcd")]),
            ..Default::default()
        };
        assert_eq!(
            redactor(&cfg).redact("abcde").text,
            "[redacted:value:EARLY]"
        );
    }

    #[test]
    fn an_overlapping_value_extends_the_earlier_pattern_span() {
        // The bearer class stops at `!`, so the value candidate starts inside the
        // pattern span and ends past it. Extending the kept span leaves no tail.
        let value = "abcdefghijk1234567890!QRSTUVWXYZ";
        let cfg = RedactConfig {
            values: values(&[("MY_TOKEN", value)]),
            ..Default::default()
        };
        let out = redactor(&cfg).redact(&format!("Authorization: Bearer {value}"));
        assert_eq!(out.text, "Authorization: [redacted:bearer]");
        assert_eq!(
            out.notices,
            vec![Notice {
                kind: Kind::Pattern,
                label: "bearer".into(),
                count: 1,
            }]
        );
    }

    #[test]
    fn pattern_wins_a_tie_against_a_value_of_equal_length() {
        let cfg = RedactConfig {
            builtin: false,
            patterns: vec!["abc".into()],
            values: values(&[("A", "abc")]),
            ..Default::default()
        };
        let out = redactor(&cfg).redact("abc");
        assert_eq!(out.text, "[redacted:user]");
        assert_eq!(
            out.notices,
            vec![Notice {
                kind: Kind::Pattern,
                label: "user".into(),
                count: 1,
            }]
        );
    }

    #[test]
    fn redact_spans_are_sorted_non_overlapping_and_rebuild_the_text() {
        let cfg = RedactConfig {
            builtin: false,
            patterns: vec!["tok-[0-9]+".into()],
            values: values(&[("KEY", "hunter2secret")]),
            ..Default::default()
        };
        let text = "a tok-12 b hunter2secret c";
        let engine = redactor(&cfg);
        let spans = engine.redact_spans(text);
        assert_eq!(spans.len(), 2);
        assert_eq!(spans[0].kind, Kind::Pattern);
        assert_eq!(spans[1].kind, Kind::Value);
        assert!(spans[0].start < spans[1].start);
        assert!(spans[0].end <= spans[1].start);

        let mut rebuilt = String::new();
        let mut cursor = 0;
        for span in &spans {
            rebuilt.push_str(&text[cursor..span.start]);
            rebuilt.push_str(&span.replacement);
            cursor = span.end;
        }
        rebuilt.push_str(&text[cursor..]);
        assert_eq!(rebuilt, engine.redact(text).text);
    }

    #[test]
    fn notices_aggregate_per_kind_and_label_without_matched_text() {
        let token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789";
        let secret = "supersecretvalue";
        let cfg = RedactConfig {
            values: values(&[("TOKEN", secret)]),
            ..Default::default()
        };
        let text = format!("{token} and {token} and {secret}");
        let out = redactor(&cfg).redact(&text);
        assert_eq!(
            out.notices,
            vec![
                Notice {
                    kind: Kind::Pattern,
                    label: "github".into(),
                    count: 2,
                },
                Notice {
                    kind: Kind::Value,
                    label: "TOKEN".into(),
                    count: 1,
                },
            ]
        );
        for notice in &out.notices {
            let debug = format!("{notice:?}");
            assert!(!notice.label.contains(token));
            assert!(!notice.label.contains(secret));
            assert!(!debug.contains(token));
            assert!(!debug.contains(secret));
        }
        assert!(!out.text.contains(token));
        assert!(!out.text.contains(secret));
    }

    #[test]
    fn text_without_matches_is_returned_unchanged() {
        let engine = redactor(&RedactConfig::default());
        let out = engine.redact("plain text\n");
        assert_eq!(out.text, "plain text\n");
        assert!(out.notices.is_empty());
        assert!(engine.redact_spans("plain text").is_empty());
        assert_eq!(engine.redact("").text, "");
    }
}
