//! Redact secret-shaped spans from hook tool results with the shared engine.
//!
//! `apply` builds the shared `toz_core::redact::Redactor` bridge for `cfg.redact`
//! (which owns project-root and value-source resolution), redacts, and returns
//! one human-readable notice line per replaced label, for example
//! `redacted 2 values: GITHUB_TOKEN`. Notices carry labels only, never matched
//! text. Any redaction error returns the input unchanged with no notice, so the
//! hook stays fail-open.

use std::path::Path;
use toz_core::redact::Redactor;
use varde_core::redact::{Kind, Notice};

/// Redact `text` for `cfg`, returning the redacted text and one notice line per
/// replaced label.
pub fn apply(cfg: &toz_core::Config, text: &str) -> (String, Vec<String>) {
    apply_at(cfg, None, text)
}

/// `apply` against an explicit value-source root, like
/// `toz_core::redact::Redactor::from_config_at`; `None` resolves the process's
/// project root, like `apply`. Split out so tests can aim value sources at a
/// fixture directory instead of the process's project.
fn apply_at(cfg: &toz_core::Config, root: Option<&Path>, text: &str) -> (String, Vec<String>) {
    let built = match root {
        Some(root) => Redactor::from_config_at(&cfg.redact, root),
        None => Redactor::from_config(&cfg.redact),
    };
    let Ok(redactor) = built else {
        return (text.to_string(), Vec::new()); // fail open
    };
    let (text, notices) = redactor.apply_with_notices(text);
    (text, notices.iter().map(notice_line).collect())
}

/// `redacted 2 values: GITHUB_TOKEN`; labels only, never the replaced text.
fn notice_line(notice: &Notice) -> String {
    let noun = match notice.kind {
        Kind::Value => "value",
        Kind::Pattern => "pattern",
    };
    let noun = if notice.count == 1 {
        noun.to_string()
    } else {
        format!("{noun}s")
    };
    format!("redacted {} {noun}: {}", notice.count, notice.label)
}

#[cfg(test)]
mod tests {
    use super::*;
    use toz_core::config::Redact;

    const GITHUB_TOKEN: &str = "ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD";

    /// A config with `redact` set and everything else at its default.
    fn config(redact: Redact) -> toz_core::Config {
        toz_core::Config {
            redact,
            ..Default::default()
        }
    }

    /// A config that needs no value sources, so tests never read the environment
    /// or the project's `.env` files.
    fn pattern_only() -> toz_core::Config {
        config(Redact {
            values: false,
            ..Default::default()
        })
    }

    #[test]
    fn redacts_a_pattern_and_names_its_kind() {
        let (text, notices) = apply(&pattern_only(), &format!("see {GITHUB_TOKEN} end\n"));
        assert_eq!(text, "see [redacted:github] end\n");
        assert_eq!(notices, ["redacted 1 pattern: github"]);
    }

    #[test]
    fn counts_repeated_replacements_in_one_notice() {
        let (_, notices) = apply(
            &pattern_only(),
            &format!("{GITHUB_TOKEN} and {GITHUB_TOKEN}"),
        );
        assert_eq!(notices, ["redacted 2 patterns: github"]);
    }

    #[test]
    fn leaves_text_without_secrets_untouched() {
        let text = "plain output\nsecond line\n";
        assert_eq!(apply(&pattern_only(), text), (text.to_string(), Vec::new()));
    }

    #[test]
    fn an_invalid_pattern_fails_open_unchanged_without_a_notice() {
        let cfg = config(Redact {
            values: false,
            patterns: vec!["(".into()],
            ..Default::default()
        });
        let text = format!("token={GITHUB_TOKEN}\n");
        assert_eq!(apply(&cfg, &text), (text.clone(), Vec::new()));
    }

    #[test]
    fn redacts_a_secret_value_and_names_the_variable() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(
            dir.path().join(".env"),
            "DATABASE_PASSWORD=zq9-unique-value-12345\n",
        )
        .unwrap();
        let cfg = config(Redact::default()); // value sources on
        let (text, notices) = apply_at(
            &cfg,
            Some(dir.path()),
            "connecting with zq9-unique-value-12345",
        );
        assert!(!text.contains("zq9-unique-value-12345"), "{text}");
        assert_eq!(notices, ["redacted 1 value: DATABASE_PASSWORD"]);
    }

    #[test]
    fn redacts_a_recorded_payload_stdout_under_the_capture_threshold() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(
            dir.path().join(".env"),
            "DATABASE_PASSWORD=zq9-unique-value-12345\n",
        )
        .unwrap();
        let cfg = config(Redact::default());
        // Recorded PostToolUse shape: the secret sits in `tool_response.stdout`,
        // under the capture threshold, so only redaction keeps it out of the
        // transcript.
        let payload = serde_json::json!({
            "tool_name": "Bash",
            "tool_input": {"command": "cat .env"},
            "tool_response": {
                "stdout": "DATABASE_PASSWORD is exported; connecting with zq9-unique-value-12345\n",
                "stderr": "",
            },
            "session_id": "s1",
        });
        let stdout = payload["tool_response"]["stdout"].as_str().unwrap();
        assert!(
            stdout.len() < cfg.threshold,
            "fixture must stay under the capture threshold"
        );

        let (text, notices) = apply_at(&cfg, Some(dir.path()), stdout);
        assert!(!text.contains("zq9-unique-value-12345"), "{text}");
        assert!(
            text.contains("[redacted:value:DATABASE_PASSWORD]"),
            "{text}"
        );
        assert_eq!(notices, ["redacted 1 value: DATABASE_PASSWORD"]);
        assert!(!notices[0].contains("zq9-unique"), "{notices:?}");
    }
}
