//! Opt-in, exact stdout/stderr retention, separate from searchable captures.
//!
//! Each handle names one private file containing a small versioned header followed by the exact
//! stdout and stderr bytes. The file stores the stream lengths, so no separators or text decoding
//! alter either stream.

use crate::config::{CaptureRules, RawOutputConfig};
use crate::rand;
use crate::redact::NeverCapture;
use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use thiserror::Error;

const MAGIC: &[u8; 8] = b"TOZRAW01";
const HEADER_LEN: usize = 32;
const HANDLE_HEX_LEN: usize = 32;

/// An opaque identifier for one exact-output record.
///
/// The identifier can be printed and passed back to [`RawStore::get`], but does not contain or
/// expose either output stream.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct RawHandle(String);

impl RawHandle {
    /// Parse a handle supplied explicitly by a caller.
    pub fn parse(value: &str) -> Result<Self, RawError> {
        if value.len() != HANDLE_HEX_LEN + 1
            || !value.starts_with('r')
            || !value[1..]
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(RawError::InvalidHandle);
        }
        Ok(Self(value.to_string()))
    }

    /// The printable handle token, not the stored output.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for RawHandle {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

/// Exact output bytes returned only by explicit raw-handle retrieval.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RawOutputBytes {
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
}

/// Failures while storing or retrieving an exact-output record.
#[derive(Debug, Error)]
pub enum RawError {
    #[error("exact output storage is disabled")]
    Disabled,
    #[error("exact output for source {source_key:?} is excluded by a never-capture rule")]
    Excluded { source_key: String },
    #[error("exact output is {bytes} bytes, above the configured limit of {max_bytes} bytes")]
    TooLarge { bytes: usize, max_bytes: usize },
    #[error("exact output handle {handle} has expired")]
    Expired { handle: RawHandle },
    #[error("exact output handle {handle} was not found")]
    NotFound { handle: RawHandle },
    #[error("invalid exact output handle")]
    InvalidHandle,
    #[error("exact output record is corrupt: {0}")]
    Corrupt(&'static str),
    #[error("invalid never-capture configuration: {0}")]
    InvalidRules(String),
    #[error("raw output path {path} is not a private directory")]
    InsecureDirectory { path: PathBuf },
    #[error("could not create a unique exact output handle")]
    HandleCollision,
    #[error("I/O at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
}

/// File-backed exact-output storage for one project or store directory.
pub struct RawStore {
    dir: PathBuf,
    enabled: bool,
    max_bytes: usize,
    ttl_secs: u64,
    never: NeverCapture,
}

impl RawStore {
    /// Configure raw storage without creating the directory. The configured `capture.never`
    /// rules are used to refuse matching sources before any output is written.
    pub fn open(
        dir: &Path,
        raw: &RawOutputConfig,
        capture: &CaptureRules,
    ) -> Result<Self, RawError> {
        let never = NeverCapture::from_config(capture)
            .map_err(|error| RawError::InvalidRules(error.to_string()))?;
        Ok(Self {
            dir: dir.to_path_buf(),
            enabled: raw.enabled,
            max_bytes: raw.max_bytes,
            ttl_secs: raw.ttl_secs,
            never,
        })
    }

    /// Store exact bytes using the supplied source key for never-capture matching.
    pub fn store(
        &self,
        source_key: &str,
        stdout: &[u8],
        stderr: &[u8],
    ) -> Result<RawHandle, RawError> {
        self.store_with_source(source_key, source_key, stdout, stderr)
    }

    /// Store exact bytes after checking both the command source and its capture key against
    /// `capture.never`. Pass the same source and key used by the searchable capture pipeline.
    pub fn store_with_source(
        &self,
        source: &str,
        source_key: &str,
        stdout: &[u8],
        stderr: &[u8],
    ) -> Result<RawHandle, RawError> {
        self.store_at(source, source_key, stdout, stderr, crate::store::now())
    }

    fn store_at(
        &self,
        source: &str,
        source_key: &str,
        stdout: &[u8],
        stderr: &[u8],
        now: i64,
    ) -> Result<RawHandle, RawError> {
        self.validate_store(source, source_key, stdout, stderr)?;
        prepare_private_dir(&self.dir)?;
        let ttl = i64::try_from(self.ttl_secs).unwrap_or(i64::MAX);
        let expires_at = now.saturating_add(ttl);

        for _ in 0..8 {
            let handle = new_handle();
            let path = self.path_for(&handle);
            let Some(mut file) = create_raw_file(&path)? else {
                continue;
            };
            if let Err(source) = write_raw_record(&mut file, expires_at, stdout, stderr) {
                let _ = fs::remove_file(&path);
                return Err(io_error(path, source));
            }
            return Ok(handle);
        }
        Err(RawError::HandleCollision)
    }

    fn validate_store(
        &self,
        source: &str,
        source_key: &str,
        stdout: &[u8],
        stderr: &[u8],
    ) -> Result<(), RawError> {
        if !self.enabled {
            return Err(RawError::Disabled);
        }
        if self.never.matches(source_key) || self.never.matches(source) {
            return Err(RawError::Excluded {
                source_key: source_key.to_string(),
            });
        }
        let bytes = stdout.len().saturating_add(stderr.len());
        if stdout.len().checked_add(stderr.len()).is_none() || bytes > self.max_bytes {
            return Err(RawError::TooLarge {
                bytes,
                max_bytes: self.max_bytes,
            });
        }
        Ok(())
    }

    /// Retrieve the exact bytes for one explicitly supplied handle.
    pub fn get(&self, handle: &RawHandle) -> Result<RawOutputBytes, RawError> {
        self.get_at(handle, crate::store::now())
    }

    fn get_at(&self, handle: &RawHandle, now: i64) -> Result<RawOutputBytes, RawError> {
        let path = self.path_for(handle);
        let mut file = File::open(&path).map_err(|error| {
            if error.kind() == io::ErrorKind::NotFound {
                RawError::NotFound {
                    handle: handle.clone(),
                }
            } else {
                io_error(path.clone(), error)
            }
        })?;

        let mut header = [0u8; HEADER_LEN];
        file.read_exact(&mut header)
            .map_err(|error| io_or_corrupt(path.clone(), error))?;
        let (expires_at, stdout_len, stderr_len) = parse_header(&header)?;
        if now >= expires_at {
            // Report the expiry once, then remove the exact bytes on access.
            let _ = fs::remove_file(&path);
            return Err(RawError::Expired {
                handle: handle.clone(),
            });
        }

        self.read_raw_output(file, path, stdout_len, stderr_len)
    }

    fn read_raw_output(
        &self,
        mut file: File,
        path: PathBuf,
        stdout_len: u64,
        stderr_len: u64,
    ) -> Result<RawOutputBytes, RawError> {
        let total = stdout_len
            .checked_add(stderr_len)
            .ok_or(RawError::TooLarge {
                bytes: usize::MAX,
                max_bytes: self.max_bytes,
            })?;
        let bytes = usize::try_from(total).unwrap_or(usize::MAX);
        if bytes > self.max_bytes {
            return Err(RawError::TooLarge {
                bytes,
                max_bytes: self.max_bytes,
            });
        }
        let expected_file_len = (HEADER_LEN as u64)
            .checked_add(total)
            .ok_or(RawError::Corrupt("file length overflow"))?;
        let actual_file_len = file
            .metadata()
            .map_err(|error| io_error(path.clone(), error))?
            .len();
        if actual_file_len != expected_file_len {
            return Err(RawError::Corrupt("stream lengths do not match file length"));
        }
        let stdout_len = usize::try_from(stdout_len)
            .map_err(|_| RawError::Corrupt("stdout length is unsupported on this platform"))?;
        let stderr_len = usize::try_from(stderr_len)
            .map_err(|_| RawError::Corrupt("stderr length is unsupported on this platform"))?;
        let mut stdout = vec![0; stdout_len];
        let mut stderr = vec![0; stderr_len];
        file.read_exact(&mut stdout)
            .map_err(|error| io_error(path.clone(), error))?;
        file.read_exact(&mut stderr)
            .map_err(|error| io_error(path, error))?;
        Ok(RawOutputBytes { stdout, stderr })
    }

    /// Remove records whose configured lifetime has elapsed. Returns the number removed.
    pub fn prune(&self) -> Result<usize, RawError> {
        self.prune_at(crate::store::now())
    }

    fn prune_at(&self, now: i64) -> Result<usize, RawError> {
        let entries = match fs::read_dir(&self.dir) {
            Ok(entries) => entries,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(0),
            Err(source) => return Err(io_error(self.dir.clone(), source)),
        };

        let mut removed = 0;
        for entry in entries {
            let entry = entry.map_err(|error| io_error(self.dir.clone(), error))?;
            let path = entry.path();
            let Some(value) = entry.file_name().to_str().map(str::to_owned) else {
                continue;
            };
            let Ok(handle) = RawHandle::parse(&value) else {
                continue;
            };
            if !entry
                .file_type()
                .map_err(|error| io_error(path.clone(), error))?
                .is_file()
            {
                continue;
            }
            let Ok(mut file) = File::open(&path) else {
                continue;
            };
            let mut header = [0u8; HEADER_LEN];
            if file.read_exact(&mut header).is_err() {
                continue;
            }
            let Ok((expires_at, _, _)) = parse_header(&header) else {
                continue;
            };
            if now >= expires_at {
                match fs::remove_file(&path) {
                    Ok(()) => removed += 1,
                    Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                    Err(source) => return Err(io_error(path, source)),
                }
            }
            let _ = handle;
        }
        Ok(removed)
    }

    fn path_for(&self, handle: &RawHandle) -> PathBuf {
        self.dir.join(handle.as_str())
    }
}

fn create_raw_file(path: &Path) -> Result<Option<File>, RawError> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    match options.open(path) {
        Ok(file) => Ok(Some(file)),
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => Ok(None),
        Err(source) => Err(io_error(path.to_path_buf(), source)),
    }
}

fn write_raw_record(
    file: &mut File,
    expires_at: i64,
    stdout: &[u8],
    stderr: &[u8],
) -> io::Result<()> {
    file.write_all(MAGIC)?;
    file.write_all(&expires_at.to_le_bytes())?;
    file.write_all(&(stdout.len() as u64).to_le_bytes())?;
    file.write_all(&(stderr.len() as u64).to_le_bytes())?;
    file.write_all(stdout)?;
    file.write_all(stderr)?;
    file.sync_all()
}

fn new_handle() -> RawHandle {
    // The private directory provides the access control; the token only needs collision
    // resistance for the owner's local store.
    RawHandle(format!(
        "r{:016x}{:016x}",
        rand::next_u64(),
        rand::next_u64()
    ))
}

fn parse_header(header: &[u8; HEADER_LEN]) -> Result<(i64, u64, u64), RawError> {
    if &header[..MAGIC.len()] != MAGIC {
        return Err(RawError::Corrupt("unrecognized format"));
    }
    let expires_at = i64::from_le_bytes(header[8..16].try_into().unwrap());
    let stdout_len = u64::from_le_bytes(header[16..24].try_into().unwrap());
    let stderr_len = u64::from_le_bytes(header[24..32].try_into().unwrap());
    Ok((expires_at, stdout_len, stderr_len))
}

fn prepare_private_dir(path: &Path) -> Result<(), RawError> {
    fs::create_dir_all(path).map_err(|error| io_error(path.to_path_buf(), error))?;
    let metadata =
        fs::symlink_metadata(path).map_err(|error| io_error(path.to_path_buf(), error))?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(RawError::InsecureDirectory {
            path: path.to_path_buf(),
        });
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o700))
            .map_err(|error| io_error(path.to_path_buf(), error))?;
    }
    Ok(())
}

fn io_error(path: PathBuf, source: io::Error) -> RawError {
    RawError::Io { path, source }
}

fn io_or_corrupt(path: PathBuf, source: io::Error) -> RawError {
    if source.kind() == io::ErrorKind::UnexpectedEof {
        RawError::Corrupt("header is truncated")
    } else {
        io_error(path, source)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{CaptureRules, Config, RawOutputConfig};

    fn enabled_config() -> RawOutputConfig {
        RawOutputConfig {
            enabled: true,
            ..RawOutputConfig::default()
        }
    }

    fn store(dir: &Path, config: &RawOutputConfig, capture: &CaptureRules) -> RawStore {
        RawStore::open(dir, config, capture).unwrap()
    }

    #[test]
    fn default_config_is_opt_in_with_one_hour_ttl() {
        let cfg = Config::default();
        assert!(!cfg.raw.enabled);
        assert_eq!(cfg.raw.ttl_secs, 3600);
        assert_eq!(cfg.raw.max_bytes, 20 * 1024 * 1024);

        let parsed: Config =
            toml::from_str("[raw]\nenabled = true\nmax_bytes = 4096\nttl_secs = 90\n").unwrap();
        assert!(parsed.raw.enabled);
        assert_eq!(parsed.raw.max_bytes, 4096);
        assert_eq!(parsed.raw.ttl_secs, 90);
    }

    #[test]
    fn exact_binary_streams_round_trip_under_an_explicit_handle() {
        let temp = tempfile::tempdir().unwrap();
        let raw = store(
            &temp.path().join("raw"),
            &enabled_config(),
            &CaptureRules::default(),
        );
        let stdout = [0, 0xff, b'\n', 0x80];
        let stderr = [b'e', 0, b'\n'];

        let handle = raw.store("cargo test", &stdout, &stderr).unwrap();
        let parsed = RawHandle::parse(handle.as_str()).unwrap();
        assert_eq!(parsed, handle);
        let output = raw.get(&parsed).unwrap();
        assert_eq!(output.stdout, stdout);
        assert_eq!(output.stderr, stderr);
    }

    #[test]
    fn disabled_excluded_and_too_large_outputs_are_distinct_errors() {
        let temp = tempfile::tempdir().unwrap();
        let disabled = store(
            &temp.path().join("disabled"),
            &RawOutputConfig::default(),
            &CaptureRules::default(),
        );
        assert!(matches!(
            disabled.store("cargo test", b"out", b"err"),
            Err(RawError::Disabled)
        ));

        let rules = CaptureRules {
            never: vec!["cargo secret*".into()],
            builtin_never: false,
        };
        let limited_config = RawOutputConfig {
            max_bytes: 4,
            ..enabled_config()
        };
        let raw = store(&temp.path().join("raw"), &limited_config, &rules);
        assert!(matches!(
            raw.store("cargo secret read", b"out", b"err"),
            Err(RawError::Excluded { .. })
        ));
        assert!(matches!(
            raw.store("cargo test", b"123", b"45"),
            Err(RawError::TooLarge {
                bytes: 5,
                max_bytes: 4
            })
        ));
        assert!(!temp.path().join("raw").exists());
    }

    #[test]
    fn source_and_capture_key_are_both_excluded() {
        let temp = tempfile::tempdir().unwrap();
        let rules = CaptureRules {
            never: vec!["kubectl get secret*".into()],
            builtin_never: false,
        };
        let raw = store(&temp.path().join("raw"), &enabled_config(), &rules);
        assert!(matches!(
            raw.store_with_source("kubectl get secret prod", "diagnostic label", b"out", b""),
            Err(RawError::Excluded { .. })
        ));
        assert!(matches!(
            raw.store_with_source("safe command", "kubectl get secret prod", b"out", b""),
            Err(RawError::Excluded { .. })
        ));
    }

    #[test]
    fn expired_records_return_expired_and_pruning_removes_them() {
        let temp = tempfile::tempdir().unwrap();
        let config = RawOutputConfig {
            ttl_secs: 10,
            ..enabled_config()
        };
        let raw = store(&temp.path().join("raw"), &config, &CaptureRules::default());
        let handle = raw
            .store_at("cargo test", "cargo test", b"out", b"err", 100)
            .unwrap();
        assert!(matches!(
            raw.get_at(&handle, 110),
            Err(RawError::Expired { .. })
        ));
        assert_eq!(raw.prune_at(110).unwrap(), 0);
        assert!(matches!(
            raw.get_at(&handle, 100),
            Err(RawError::NotFound { .. })
        ));
    }

    #[cfg(unix)]
    #[test]
    fn raw_directory_and_record_are_owner_only() {
        use std::os::unix::fs::PermissionsExt;

        let temp = tempfile::tempdir().unwrap();
        let dir = temp.path().join("raw");
        let raw = store(&dir, &enabled_config(), &CaptureRules::default());
        let handle = raw.store("cargo test", b"out", b"err").unwrap();

        assert_eq!(
            fs::metadata(&dir).unwrap().permissions().mode() & 0o777,
            0o700
        );
        assert_eq!(
            fs::metadata(dir.join(handle.as_str()))
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
    }

    #[test]
    fn invalid_handle_is_rejected_before_path_access() {
        assert!(matches!(
            RawHandle::parse("../../toz.db"),
            Err(RawError::InvalidHandle)
        ));
    }
}
