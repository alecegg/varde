//! `toz index`: store local files under a handle, remembering mtime + hash so `search` can
//! flag hits whose backing file has changed since.

use crate::capture::{self, CaptureInput, Outcome};
use crate::config::Config;
use crate::metadata;
use crate::store::Store;
use anyhow::{Context, Result};
use std::fs::Metadata;
use std::path::Path;

/// Metadata recorded alongside an indexed file.
pub struct FileMeta {
    /// Unix nanoseconds. Existing databases may contain Unix seconds.
    pub mtime: i64,
    pub hash: Vec<u8>,
}

fn modified_timestamp(md: &Metadata) -> Option<i64> {
    md.modified()
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .and_then(|d| i64::try_from(d.as_nanos()).ok())
}

pub fn file_meta(path: &Path, bytes: &[u8]) -> Result<FileMeta> {
    let md = std::fs::metadata(path).with_context(|| format!("stat {}", path.display()))?;
    let mtime = modified_timestamp(&md).unwrap_or(0);
    Ok(FileMeta {
        mtime,
        hash: blake3::hash(bytes).as_bytes().to_vec(),
    })
}

/// True when `path` no longer matches what was recorded. Cheap mtime check first; only hash
/// the file when the mtime differs (a `touch` or checkout with identical content is not stale).
/// A missing or unreadable file counts as stale.
pub fn is_stale(path: &str, mtime: Option<i64>, hash: Option<&[u8]>) -> bool {
    let p = Path::new(path);
    let Ok(md) = std::fs::metadata(p) else {
        return true;
    };
    let now_mtime = modified_timestamp(&md);
    if mtime.is_some() && now_mtime == mtime {
        return false;
    }
    match (hash, std::fs::read(p)) {
        (Some(h), Ok(bytes)) => blake3::hash(&bytes).as_bytes() != h,
        _ => true,
    }
}

/// Index one file. Always stores (force), kind `index`, source = absolute path (the supersession
/// key, so re-indexing replaces the previous capture).
pub fn index_file(
    cfg: &Config,
    store: &mut Store,
    path: &Path,
    label: Option<&str>,
    session: Option<&str>,
) -> Result<Outcome> {
    let abs = std::fs::canonicalize(path).with_context(|| format!("resolve {}", path.display()))?;
    let bytes = std::fs::read(&abs).with_context(|| format!("read {}", abs.display()))?;
    let meta = file_meta(&abs, &bytes)?;
    let source = abs.to_string_lossy().into_owned();
    let mut input = CaptureInput::new(&bytes, &source, "index");
    input.label = label;
    input.session = session;
    input.force = true;
    input.file_mtime = Some(meta.mtime);
    input.file_hash = Some(meta.hash);
    capture::run(cfg, store, input, &[])
}

/// Re-index every live `index` capture whose backing file has changed. Returns the paths
/// refreshed. Missing files are left alone (their hits keep the stale flag).
pub fn refresh_stale(
    cfg: &Config,
    store: &mut Store,
    session: Option<&str>,
) -> Result<Vec<String>> {
    let rows = store.list(usize::MAX, false)?;
    let mut refreshed = Vec::new();
    for row in rows.into_iter().filter(|r| r.kind == "index") {
        if !Path::new(&row.source).is_file() {
            continue;
        }
        if !is_stale(&row.source, row.file_mtime, row.file_hash.as_deref()) {
            continue;
        }
        // Keep an explicit user label (it is also the supersession key). The display label may
        // be truncated, so the stored source key is the reliable record of whether one exists.
        let stored_source_key: String = store.conn().query_row(
            "SELECT source_key FROM captures WHERE id = ?1",
            [row.id],
            |record| record.get(0),
        )?;
        let default_key = capture::source_key(&row.source);
        let label = if stored_source_key == default_key
            || stored_source_key
                == metadata::identity_at(store.path().parent().unwrap(), &default_key)?
        {
            None
        } else if stored_source_key == row.label
            || stored_source_key
                == metadata::identity_at(store.path().parent().unwrap(), &row.label)?
        {
            Some(row.label.as_str())
        } else {
            // The original explicit label was redacted and cannot be reconstructed.
            continue;
        };
        if index_file(cfg, store, Path::new(&row.source), label, session).is_ok() {
            refreshed.push(row.source.clone());
        }
    }
    Ok(refreshed)
}

/// Index raw bytes (stdin) under `source`.
pub fn index_bytes(
    cfg: &Config,
    store: &mut Store,
    bytes: &[u8],
    source: &str,
    label: Option<&str>,
    session: Option<&str>,
) -> Result<Outcome> {
    let mut input = CaptureInput::new(bytes, source, "index");
    input.label = label;
    input.session = session;
    input.force = true;
    capture::run(cfg, store, input, &[])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sensitive_index_path_is_masked_and_requires_explicit_reindex() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("vault-123.txt");
        std::fs::write(&path, "original body").unwrap();
        let mut store = Store::open(&dir.path().join("toz.db")).unwrap();
        let mut cfg = Config::default();
        cfg.redact.patterns.push("vault-[0-9]+".into());
        index_file(&cfg, &mut store, &path, None, None).unwrap();
        let row = store.list(1, false).unwrap().remove(0);
        assert!(!row.source.contains("vault-123"));
        std::fs::write(&path, "changed body").unwrap();
        assert!(refresh_stale(&cfg, &mut store, None).unwrap().is_empty());
        index_file(&cfg, &mut store, &path, None, None).unwrap();
        assert_eq!(store.list(1, false).unwrap().len(), 1);
    }

    #[test]
    fn redacted_explicit_index_label_does_not_create_a_second_live_capture() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("ordinary.txt");
        std::fs::write(&path, "original body").unwrap();
        let mut store = Store::open(&dir.path().join("toz.db")).unwrap();
        let mut cfg = Config::default();
        cfg.redact.patterns.push("vault-[0-9]+".into());
        index_file(&cfg, &mut store, &path, Some("label vault-123"), None).unwrap();
        std::fs::write(&path, "changed body").unwrap();
        assert!(refresh_stale(&cfg, &mut store, None).unwrap().is_empty());
        assert_eq!(store.list(10, false).unwrap().len(), 1);
    }

    #[test]
    fn stale_tracks_content_not_just_mtime() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("f.txt");
        std::fs::write(&p, "hello").unwrap();
        let meta = file_meta(&p, b"hello").unwrap();
        let ps = p.to_string_lossy().into_owned();
        assert!(!is_stale(&ps, Some(meta.mtime), Some(&meta.hash)));
        // Different mtime, same content → not stale.
        assert!(!is_stale(&ps, Some(meta.mtime - 100), Some(&meta.hash)));
        std::fs::write(&p, "changed").unwrap();
        assert!(is_stale(&ps, Some(meta.mtime - 100), Some(&meta.hash)));
        std::fs::remove_file(&p).unwrap();
        assert!(is_stale(&ps, Some(meta.mtime), Some(&meta.hash)));
    }

    #[test]
    fn stale_detects_edits_within_the_same_second() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("f.txt");
        std::fs::write(&p, "hello").unwrap();
        let first_mtime = std::time::UNIX_EPOCH
            + std::time::Duration::from_secs(1_700_000_000)
            + std::time::Duration::from_nanos(100);
        let file = std::fs::File::options().write(true).open(&p).unwrap();
        file.set_modified(first_mtime).unwrap();
        let meta = file_meta(&p, b"hello").unwrap();

        std::fs::write(&p, "changed").unwrap();
        let second_mtime = first_mtime + std::time::Duration::from_nanos(100);
        let file = std::fs::File::options().write(true).open(&p).unwrap();
        file.set_modified(second_mtime).unwrap();

        assert!(is_stale(
            &p.to_string_lossy(),
            Some(meta.mtime),
            Some(&meta.hash)
        ));
    }

    #[test]
    fn legacy_second_mtime_remains_compatible() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("f.txt");
        std::fs::write(&p, "hello").unwrap();
        let meta = file_meta(&p, b"hello").unwrap();
        let legacy_mtime = meta.mtime / 1_000_000_000;
        let ps = p.to_string_lossy().into_owned();

        assert!(!is_stale(&ps, Some(legacy_mtime), Some(&meta.hash)));
        std::fs::write(&p, "changed").unwrap();
        assert!(is_stale(&ps, Some(legacy_mtime), Some(&meta.hash)));
    }

    #[test]
    fn refresh_supersedes_default_label_for_long_path() {
        let dir = tempfile::tempdir().unwrap();
        let nested = dir.path().join("a".repeat(100));
        std::fs::create_dir(&nested).unwrap();
        let path = nested.join("indexed.txt");
        std::fs::write(&path, "before").unwrap();
        let first_mtime = std::time::UNIX_EPOCH + std::time::Duration::from_secs(1_700_000_000);
        std::fs::File::options()
            .write(true)
            .open(&path)
            .unwrap()
            .set_modified(first_mtime)
            .unwrap();

        let mut store = Store::open(&dir.path().join("toz.db")).unwrap();
        let cfg = Config::default();
        index_file(&cfg, &mut store, &path, None, None).unwrap();
        let source = std::fs::canonicalize(&path)
            .unwrap()
            .to_string_lossy()
            .into_owned();
        let original = store.list(usize::MAX, false).unwrap();
        assert_eq!(original.len(), 1);
        assert_ne!(original[0].label, source);

        std::fs::write(&path, "after").unwrap();
        std::fs::File::options()
            .write(true)
            .open(&path)
            .unwrap()
            .set_modified(first_mtime + std::time::Duration::from_secs(1))
            .unwrap();

        assert_eq!(refresh_stale(&cfg, &mut store, None).unwrap(), vec![source]);
        assert_eq!(store.list(usize::MAX, false).unwrap().len(), 1);
        let all = store.list(usize::MAX, true).unwrap();
        assert_eq!(all.len(), 2);
        assert_eq!(
            all.iter().filter(|row| row.superseded_by.is_none()).count(),
            1
        );
    }
}
