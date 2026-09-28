//! Private identity keys and display-safe metadata for captures and fetches.

use crate::config::config_dir;
use crate::redact::Redactor;
use anyhow::{Context, Result};
use regex::{Captures, Regex};
use std::io::Write;
use std::path::Path;
use std::sync::OnceLock;

const KEY_FILE: &str = "metadata.key";

/// Stable, private identity for a source or explicit label.
pub fn identity(original: &str) -> Result<String> {
    keyed_hash("capture-identity", original)
}

/// Use the store's directory so a configured project store does not depend on the default config path.
pub fn identity_at(dir: &Path, original: &str) -> Result<String> {
    keyed_hash_at(dir, "capture-identity", original)
}

/// Stable, private cache filename component for the original request URL.
pub fn cache_key(url: &str) -> Result<String> {
    keyed_hash("fetch-cache", url)
}

/// Private project identity stored in fetch cache metadata.
pub fn project_identity(project_key: &str) -> Result<String> {
    keyed_hash("fetch-project", project_key)
}

fn keyed_hash(domain: &str, input: &str) -> Result<String> {
    keyed_hash_at(&config_dir()?, domain, input)
}

fn keyed_hash_at(dir: &Path, domain: &str, input: &str) -> Result<String> {
    let key = read_or_create_key(dir)?;
    let mut hasher = blake3::Hasher::new_keyed(&key);
    hasher.update(domain.as_bytes());
    hasher.update(&[0]);
    hasher.update(input.as_bytes());
    Ok(hasher.finalize().to_hex().to_string())
}

fn read_or_create_key(dir: &Path) -> Result<[u8; 32]> {
    let path = dir.join(KEY_FILE);
    if !path.exists() {
        std::fs::create_dir_all(dir).with_context(|| format!("creating {}", dir.display()))?;
        let mut key = [0u8; 32];
        getrandom::fill(&mut key).context("generating metadata identity key")?;
        let mut tmp = tempfile::NamedTempFile::new_in(dir)?;
        tmp.write_all(&key)?;
        tmp.as_file().sync_all()?;
        match tmp.persist_noclobber(&path) {
            Ok(_) => {}
            Err(err) if err.error.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(err) => return Err(err.error.into()),
        }
    }
    let bytes = std::fs::read(&path).with_context(|| format!("reading {}", path.display()))?;
    anyhow::ensure!(
        bytes.len() == 32,
        "invalid metadata identity key at {}",
        path.display()
    );
    let mut key = [0u8; 32];
    key.copy_from_slice(&bytes);
    Ok(key)
}

/// Hide credentials, query values and fragments, then apply configured patterns.
pub fn sanitize_url(redactor: &Redactor, input: &str) -> String {
    if input.contains('@') && !input.contains("://") {
        return "[redacted:url]".to_string();
    }
    let Ok(mut url) = reqwest::Url::parse(input) else {
        return match input.split_once("://") {
            Some((scheme, _)) => format!("{scheme}://[redacted:url]"),
            None if input.contains('@') => "[redacted:url]".to_string(),
            None => {
                let base = input.split_once('?').map_or(input, |(base, _)| base);
                let safe = redactor.apply(base).0;
                if input.contains('?') {
                    format!("{safe}?[redacted]")
                } else {
                    safe
                }
            }
        };
    };
    let _ = url.set_username("");
    let _ = url.set_password(None);
    if url.query().is_some() {
        let keys: Vec<_> = url.query_pairs().map(|(key, _)| key.into_owned()).collect();
        url.set_query(None);
        for key in keys {
            url.query_pairs_mut().append_pair(&key, "[redacted]");
        }
    }
    if url.fragment().is_some() {
        url.set_fragment(Some("[redacted]"));
    }
    redactor.apply(url.as_str()).0
}

/// Apply configured patterns and scrub URLs embedded in arbitrary metadata text.
pub fn sanitize_text(redactor: &Redactor, input: &str) -> String {
    static URL: OnceLock<Regex> = OnceLock::new();
    let url = URL.get_or_init(|| Regex::new(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s<>]+").unwrap());
    let safe = url.replace_all(input, |captures: &Captures<'_>| {
        sanitize_url(redactor, &captures[0])
    });
    redactor.apply(&safe).0
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Redact;

    #[test]
    fn keyed_identity_is_stable_private_and_domain_separated() {
        let dir = tempfile::tempdir().unwrap();
        let key = read_or_create_key(dir.path()).unwrap();
        assert_eq!(key, read_or_create_key(dir.path()).unwrap());
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(dir.path().join(KEY_FILE))
                .unwrap()
                .permissions()
                .mode();
            assert_eq!(mode & 0o077, 0);
        }
        let mut identity = blake3::Hasher::new_keyed(&key);
        identity.update(b"capture-identity\0secret");
        let mut cache = blake3::Hasher::new_keyed(&key);
        cache.update(b"fetch-cache\0secret");
        assert_ne!(identity.finalize(), cache.finalize());
    }

    #[test]
    fn sanitizes_embedded_urls_and_configured_secret_patterns() {
        let redactor = Redactor::from_config(&Redact {
            builtin: false,
            patterns: vec!["private42".into()],
        })
        .unwrap();
        let actual = sanitize_text(
            &redactor,
            "see https://alice:pass@host.test/a?token=secret#private42 and private42",
        );
        for secret in ["alice", "pass", "secret", "private42"] {
            assert!(!actual.contains(secret), "{actual}");
        }
        assert!(actual.contains("host.test/a"));
        assert!(actual.contains("[redacted:user]"));
        assert_eq!(
            sanitize_url(&redactor, "https://alice:pass@invalid host/?key=secret"),
            "https://[redacted:url]"
        );
        assert_eq!(
            sanitize_url(&redactor, "bad?token=secret"),
            "bad?[redacted]"
        );
        assert_eq!(sanitize_url(&redactor, "alice:pass@bad"), "[redacted:url]");
        let quoted = sanitize_text(&redactor, "task https://h.test/?token=abc'def");
        assert!(!quoted.contains("abc"), "{quoted}");
        assert!(!quoted.contains("def"), "{quoted}");
    }
}
