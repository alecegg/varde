//! Secret handling: redaction on ingest and the never-capture list.
//!
//! Redaction delegates to the shared `varde_core::redact` engine; this module
//! keeps the configuration bridge, the streaming spool path and `NeverCapture`.

use crate::config::{CaptureRules, Redact};
use anyhow::{Context, Result};
use regex::Regex;
use std::fs::File;
use std::io::{Seek, Write};
use std::path::{Path, PathBuf};
use varde_core::redact::{values, Notice, RedactConfig, Redactor as Engine};

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
    engine: Engine,
}

impl Redactor {
    /// Build a redactor for `cfg`, resolving value sources against `root`: the
    /// `.env` and `.env.*` files directly under it, plus `cfg.dotenv` paths
    /// (relative ones against `root`).
    pub fn from_config_at(cfg: &Redact, root: &Path) -> Result<Self> {
        Self::build(cfg, Some(root))
    }

    /// Build a redactor for `cfg` against the project root: the git root of the
    /// current directory, or that directory itself outside a repo. When the root
    /// cannot be resolved and value sources are needed, they are skipped rather
    /// than failing the whole redactor.
    pub fn from_config(cfg: &Redact) -> Result<Self> {
        let root = if cfg.values { project_root() } else { None };
        Self::build(cfg, root.as_deref())
    }

    /// Shared builder: value sources are read only when `cfg.values` is set and a
    /// root is available.
    fn build(cfg: &Redact, root: Option<&Path>) -> Result<Self> {
        let mut redact_values = Vec::new();
        if let (true, Some(root)) = (cfg.values, root) {
            redact_values = values::collect(root);
            for path in &cfg.dotenv {
                redact_values.extend(values::from_dotenv(&root.join(path)));
            }
        }
        let engine = Engine::new(&RedactConfig {
            builtin: cfg.builtin,
            patterns: cfg.patterns.clone(),
            values: redact_values,
            reveal: cfg.reveal,
        })
        .map_err(anyhow::Error::msg)?;
        Ok(Self { engine })
    }

    /// Returns the redacted text and the engine notices: one entry per replaced
    /// `(kind, label)`, with its count. Notices never carry matched text.
    pub fn apply_with_notices(&self, text: &str) -> (String, Vec<Notice>) {
        let redacted = self.engine.redact(text);
        (redacted.text, redacted.notices)
    }

    /// Returns the redacted text and the number of replacements made.
    pub fn apply(&self, text: &str) -> (String, usize) {
        let (text, notices) = self.apply_with_notices(text);
        let count = notices.iter().map(|notice| notice.count).sum();
        (text, count)
    }

    /// Normalize into a private spool, then redact the entire stream before chunking.
    pub(crate) fn apply_spooled(
        &self,
        normalize: impl FnOnce(&mut dyn Write) -> Result<usize>,
    ) -> Result<(File, usize)> {
        let mut input = tempfile::tempfile()?;
        let mut count = normalize(&mut input)?;
        // SAFETY: these unlinked files are created internally. The normalizer
        // receives only dyn Write, never a handle or path to clone/expose.
        // No file is mutated while mapped, and the map drops before replacement.
        let map = if input.metadata()?.len() == 0 {
            None
        } else {
            Some(unsafe { memmap2::Mmap::map(&input)? })
        };
        let bytes = map.as_deref().unwrap_or_default();
        let spans = self.engine.redact_spans(std::str::from_utf8(bytes)?);
        if !spans.is_empty() {
            let mut output = tempfile::tempfile()?;
            let mut end = 0;
            for span in &spans {
                output.write_all(&bytes[end..span.start])?;
                output.write_all(span.replacement.as_bytes())?;
                end = span.end;
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

/// The project root for value-source discovery: the git root of the current
/// directory, or that directory itself outside a repo. `None` when neither can be
/// read (for example, a deleted working directory).
fn project_root() -> Option<PathBuf> {
    crate::project::Project::resolve(None)
        .map(|project| project.root)
        .or_else(|_| std::env::current_dir())
        .ok()
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
    fn configured_dotenv_values_are_redacted() {
        let dir = tempfile::tempdir().unwrap();
        let env_file = dir.path().join("custom.env");
        std::fs::write(
            &env_file,
            "ANYNAME=zq9-unique-value-12345
",
        )
        .unwrap();
        let cfg = Redact {
            builtin: false,
            dotenv: vec![env_file.to_string_lossy().into_owned()],
            ..Default::default()
        };
        let (text, count) = Redactor::from_config(&cfg)
            .unwrap()
            .apply("x zq9-unique-value-12345 y");
        assert!(!text.contains("zq9-unique"), "{text}");
        assert_eq!(count, 1);
    }

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
                ..Default::default()
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
    fn apply_with_notices_names_the_label_and_count_without_the_match() {
        let (out, notices) =
            redactor().apply_with_notices("see ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD end");
        assert!(!out.contains("ghp_"), "{out}");
        assert_eq!(notices.len(), 1);
        assert_eq!(notices[0].kind, varde_core::redact::Kind::Pattern);
        assert_eq!(notices[0].label, "github");
        assert_eq!(notices[0].count, 1);
    }

    #[test]
    fn redacts_env_assignment_but_not_ordinary_vars() {
        let (out, n) = redactor().apply("DATABASE_PASSWORD=hunter2\nPATH=/usr/bin\n");
        assert_eq!(n, 1);
        assert!(out.contains("PATH=/usr/bin"));
        assert!(!out.contains("hunter2"));
    }

    #[test]
    fn overlapping_builtins_resolve_to_one_span() {
        // The engine resolves all rules in one pass: a `Bearer sk-…` line is one
        // `bearer` span, not a `bearer` plus an inner `api-key`.
        let (bearer, bearer_count) =
            redactor().apply("Authorization: Bearer sk-ant-abcdefghijklmnopqrstuvwx");
        assert_eq!(bearer, "Authorization: [redacted:bearer]");
        assert_eq!(bearer_count, 1);

        // A `TOKEN=ghp_…` line is one `env-assign` span, not two replacements.
        let (token, token_count) =
            redactor().apply("GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789");
        assert_eq!(token, "[redacted:env-assign]");
        assert_eq!(token_count, 1);
    }

    #[test]
    fn dotenv_discovery_uses_the_given_root() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join(".env"), "TOKEN=zq9-unique-value-12345\n").unwrap();
        let cfg = Redact {
            builtin: false,
            ..Default::default()
        };
        let (text, count) = Redactor::from_config_at(&cfg, dir.path())
            .unwrap()
            .apply("x zq9-unique-value-12345 y");
        assert!(!text.contains("zq9-unique"), "{text}");
        assert_eq!(count, 1);
    }

    #[test]
    fn relative_dotenv_paths_resolve_against_the_given_root() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(
            dir.path().join("custom.env"),
            "ANYNAME=zq9-unique-value-12345\n",
        )
        .unwrap();
        let cfg = Redact {
            builtin: false,
            dotenv: vec!["custom.env".into()],
            ..Default::default()
        };
        let (text, count) = Redactor::from_config_at(&cfg, dir.path())
            .unwrap()
            .apply("x zq9-unique-value-12345 y");
        assert!(!text.contains("zq9-unique"), "{text}");
        assert_eq!(count, 1);
    }

    #[test]
    fn git_shas_untouched() {
        let (_, n) = redactor().apply("commit 3f2a9c1d8e7b6a5f4c3d2e1f0a9b8c7d6e5f4a3b");
        assert_eq!(n, 0);
    }

    #[test]
    fn from_config_without_value_sources_survives_a_deleted_cwd() {
        // The redactor only needs the project root to find value sources; without
        // `values` it must build even when the cwd is gone (fail-open, like the
        // value readers). The helper runs in its own process so the deletion
        // cannot disturb other tests.
        let exe = std::env::current_exe().unwrap();
        let status = std::process::Command::new(&exe)
            .args([
                "--exact",
                "redact::tests::deleted_cwd_helper_builds_a_pattern_only_redactor",
                "--ignored",
            ])
            .status()
            .unwrap();
        assert!(status.success(), "helper process failed: {status}");
    }

    #[test]
    #[ignore = "helper process for from_config_without_value_sources_survives_a_deleted_cwd"]
    fn deleted_cwd_helper_builds_a_pattern_only_redactor() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().to_path_buf();
        std::env::set_current_dir(&path).unwrap();
        std::fs::remove_dir_all(&path).unwrap();
        assert!(
            std::env::current_dir().is_err(),
            "the current directory should be gone"
        );
        let redactor = Redactor::from_config(&Redact {
            values: false,
            ..Default::default()
        })
        .expect("pattern-only config builds with a deleted cwd");
        let (text, count) = redactor.apply("ghp_abcdefghijklmnopqrstuvwxyz0123456789");
        assert_eq!(count, 1);
        assert!(!text.contains("ghp_"), "{text}");
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
