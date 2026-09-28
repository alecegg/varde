//! Secret handling: redaction on ingest and the never-capture list.

use crate::config::{CaptureRules, Redact};
use anyhow::{Context, Result};
use regex::Regex;
use std::fs::File;
use std::io::{Seek, Write};

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

const BUILTIN_NEVER: &[&str] = &[
    "env",
    "printenv",
    "printenv *",
    "cat *.env*",
    "gh auth token*",
    "*secret*",
    "aws configure *",
    "kubectl get secret*",
];

pub struct Redactor {
    rules: Vec<(String, Regex)>,
}

impl Redactor {
    pub fn from_config(cfg: &Redact) -> Result<Self> {
        let mut rules = Vec::new();
        if cfg.builtin {
            for (kind, pat) in BUILTIN {
                rules.push((kind.to_string(), Regex::new(pat).expect("builtin regex")));
            }
        }
        for pat in &cfg.patterns {
            let re = Regex::new(pat).with_context(|| format!("redact pattern {pat:?}"))?;
            rules.push(("user".to_string(), re));
        }
        Ok(Self { rules })
    }

    /// Returns the redacted text and the number of replacements made.
    pub fn apply(&self, text: &str) -> (String, usize) {
        let mut out = text.to_string();
        let mut count = 0;
        for (kind, re) in &self.rules {
            let replacement = format!("[redacted:{kind}]");
            let n = re.find_iter(&out).count();
            if n > 0 {
                count += n;
                out = re.replace_all(&out, replacement.as_str()).into_owned();
            }
        }
        (out, count)
    }

    /// Normalize into a private spool, then redact the entire stream before chunking.
    pub(crate) fn apply_spooled(
        &self,
        normalize: impl FnOnce(&mut dyn Write) -> Result<usize>,
    ) -> Result<(File, usize)> {
        let mut input = tempfile::tempfile()?;
        let mut count = normalize(&mut input)?;
        for (kind, re) in &self.rules {
            // SAFETY: these unlinked files are created internally. The normalizer
            // receives only dyn Write, never a handle or path to clone/expose.
            // No file is mutated while mapped, and maps drop before replacement.
            let map = if input.metadata()?.len() == 0 {
                None
            } else {
                Some(unsafe { memmap2::Mmap::map(&input)? })
            };
            let bytes = map.as_deref().unwrap_or_default();
            let text = std::str::from_utf8(bytes)?;
            let mut matches = re.find_iter(text).peekable();
            if matches.peek().is_none() {
                continue;
            }
            let mut output = tempfile::tempfile()?;
            let replacement = format!("[redacted:{kind}]");
            let mut end = 0;
            for matched in matches {
                output.write_all(&bytes[end..matched.start()])?;
                output.write_all(replacement.as_bytes())?;
                end = matched.end();
                count += 1;
            }
            output.write_all(&bytes[end..])?;
            drop(map);
            input = output;
        }
        input.rewind()?;
        Ok((input, count))
    }
}

pub struct NeverCapture {
    patterns: Vec<Regex>,
}

impl NeverCapture {
    pub fn from_config(cfg: &CaptureRules) -> Result<Self> {
        let mut patterns = Vec::new();
        if cfg.builtin_never {
            for p in BUILTIN_NEVER {
                patterns.push(glob_to_regex(p)?);
            }
        }
        for p in &cfg.never {
            patterns.push(glob_to_regex(p)?);
        }
        Ok(Self { patterns })
    }

    pub fn matches(&self, source_key: &str) -> bool {
        let key = source_key.trim();
        self.patterns.iter().any(|re| re.is_match(key))
    }
}

/// `*` → `.*`, everything else literal, anchored both ends, case-insensitive.
fn glob_to_regex(glob: &str) -> Result<Regex> {
    let mut s = String::from("(?i)^");
    for ch in glob.chars() {
        if ch == '*' {
            s.push_str(".*");
        } else {
            s.push_str(&regex::escape(&ch.to_string()));
        }
    }
    s.push('$');
    Regex::new(&s).with_context(|| format!("never-capture pattern {glob:?}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;

    #[test]
    fn spooled_redaction_matches_whole_text_rules() {
        for text in ["", "BEGIN\nsecret\nEND\ntail\n", "unmatched\n", "é\n"] {
            let cfg = Redact {
                builtin: false,
                patterns: vec![
                    r"(?s)\ABEGIN.*?END".into(),
                    r"\[redacted:user\]".into(),
                    "(?m)$".into(),
                ],
            };
            let redactor = Redactor::from_config(&cfg).unwrap();
            let (mut file, count) = redactor
                .apply_spooled(|output| {
                    output.write_all(text.as_bytes())?;
                    Ok(0)
                })
                .unwrap();
            let mut actual = String::new();
            file.read_to_string(&mut actual).unwrap();
            assert!(!actual.contains("secret"));
            assert_eq!((actual, count), redactor.apply(text));
        }
    }

    fn redactor() -> Redactor {
        Redactor::from_config(&Redact::default()).unwrap()
    }

    #[test]
    fn redacts_github_token() {
        let (out, n) = redactor().apply("see ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD end");
        assert_eq!(n, 1);
        assert!(out.contains("[redacted:github]"));
        assert!(!out.contains("ghp_"));
    }

    #[test]
    fn redacts_env_assignment_but_not_ordinary_vars() {
        let (out, n) = redactor().apply("DATABASE_PASSWORD=hunter2\nPATH=/usr/bin\n");
        assert_eq!(n, 1);
        assert!(out.contains("PATH=/usr/bin"));
        assert!(!out.contains("hunter2"));
    }

    #[test]
    fn git_shas_untouched() {
        let (_, n) = redactor().apply("commit 3f2a9c1d8e7b6a5f4c3d2e1f0a9b8c7d6e5f4a3b");
        assert_eq!(n, 0);
    }

    #[test]
    fn never_capture_globs() {
        let nc = NeverCapture::from_config(&CaptureRules::default()).unwrap();
        assert!(nc.matches("env"));
        assert!(nc.matches("cat .env.local"));
        assert!(nc.matches("gh auth token"));
        assert!(nc.matches("kubectl get secrets -n prod"));
        assert!(!nc.matches("cargo test"));
        assert!(!nc.matches("environment"));
    }
}
