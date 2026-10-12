//! Session-scoped context threshold crossing state for session-notes nudges.

use fs4::FileExt;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use varde_learn_core::diagnose::{ContextUsageHarness, context_usage};
use varde_workflow_core::memory::{
    Config, LEGACY_HANDOFF_FILE, LEGACY_HANDOFFS_DIR, MemoryPaths, NOTES_FILE, SESSION_NOTES_DIR,
};

const MAX_SESSION_ID: usize = 256;
const DEFAULT_NOTES_AT_TOKENS: u64 = 250_000;
static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, Clone, Serialize, Deserialize)]
struct SessionState {
    harness: String,
    session_id: String,
    #[serde(alias = "handoff_path")]
    notes_path: PathBuf,
    above_threshold: bool,
}

fn session_hash(session_id: &str) -> String {
    format!("{:x}", Sha256::digest(session_id.as_bytes()))
}

/// Accept only bounded printable IDs so they cannot control file paths or logs.
pub fn validate_session_id(value: &str) -> Option<&str> {
    (!value.is_empty() && value.len() <= MAX_SESSION_ID && value.chars().all(|ch| !ch.is_control()))
        .then_some(value)
}

fn store_paths(harness: &str, session_id: &str) -> Option<(PathBuf, PathBuf)> {
    let config = varde_workflow_core::memory::config_path();
    let root = config.parent()?.join("sessions");
    let key = format!("{}-{}", harness, session_hash(session_id));
    Some((
        root.join(format!("{key}.json")),
        root.join(format!("{key}.lock")),
    ))
}

fn utc_date() -> String {
    std::process::Command::new("date")
        .args(["-u", "+%Y-%m-%d"])
        .output()
        .ok()
        .filter(|output| output.status.success())
        .and_then(|output| String::from_utf8(output.stdout).ok())
        .map(|value| value.trim().to_owned())
        .filter(|value| value.len() == 10)
        .unwrap_or_else(|| "1970-01-01".to_owned())
}

fn find_existing_note(working: &Path, suffix: &str) -> Option<PathBuf> {
    for (directory, filename) in [
        (SESSION_NOTES_DIR, NOTES_FILE),
        (LEGACY_HANDOFFS_DIR, LEGACY_HANDOFF_FILE),
    ] {
        let Ok(entries) = fs::read_dir(working.join(directory)) else {
            continue;
        };
        let mut matches: Vec<_> = entries
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .filter(|path| {
                let candidate = path.join(filename);
                candidate.is_file() && valid_note_path(&candidate, working, suffix)
            })
            .collect();
        matches.sort();
        if let Some(dir) = matches.into_iter().next() {
            return Some(dir.join(filename));
        }
    }
    None
}

fn valid_note_path(path: &Path, working: &Path, suffix: &str) -> bool {
    let Some(filename) = path.file_name().and_then(|name| name.to_str()) else {
        return false;
    };
    let Some(parent) = path.parent().and_then(Path::parent) else {
        return false;
    };
    let Some(session_dir) = path
        .parent()
        .and_then(Path::file_name)
        .and_then(|name| name.to_str())
    else {
        return false;
    };
    let valid_root = match (parent, filename) {
        (root, NOTES_FILE) => root == working.join(SESSION_NOTES_DIR),
        (root, LEGACY_HANDOFF_FILE) => root == working.join(LEGACY_HANDOFFS_DIR),
        _ => false,
    };
    path.is_absolute()
        && valid_root
        && session_dir.ends_with(suffix)
        && path
            .canonicalize()
            .ok()
            .zip(parent.canonicalize().ok())
            .is_none_or(|(path, root)| path.starts_with(root))
}

fn resolve_note_path(path: &Path, working: &Path, suffix: &str) -> Option<PathBuf> {
    if !valid_note_path(path, working, suffix) {
        return None;
    }
    if path.file_name().and_then(|name| name.to_str()) == Some(LEGACY_HANDOFF_FILE)
        && !path.exists()
    {
        let session_dir = path.parent()?.file_name()?;
        let migrated_dir = working.join(SESSION_NOTES_DIR).join(session_dir);
        if migrated_dir.is_dir() {
            return Some(migrated_dir.join(NOTES_FILE));
        }
    }
    Some(path.to_owned())
}

fn with_state<T>(
    harness: &str,
    session_id: &str,
    update: impl FnOnce(&mut SessionState) -> T,
) -> Option<T> {
    let cwd = std::env::current_dir().ok()?;
    let working = MemoryPaths::resolve(&cwd).ok()?.working.path;
    let suffix = format!("session-{}", session_hash(session_id));
    let (state_path, lock_path) = store_paths(harness, session_id)?;
    fs::create_dir_all(state_path.parent()?).ok()?;
    let lock = OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .open(lock_path)
        .ok()?;
    <File as FileExt>::try_lock(&lock).ok()?;

    let mut state = fs::read(&state_path)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<SessionState>(&bytes).ok())
        .filter(|state| state.harness == harness && state.session_id == session_id)
        .and_then(|mut state| {
            state.notes_path = resolve_note_path(&state.notes_path, &working, &suffix)?;
            Some(state)
        })
        .unwrap_or_else(|| {
            let notes_path = find_existing_note(&working, &suffix).unwrap_or_else(|| {
                working
                    .join(SESSION_NOTES_DIR)
                    .join(format!("{}-{suffix}", utc_date()))
                    .join(NOTES_FILE)
            });
            SessionState {
                harness: harness.to_owned(),
                session_id: session_id.to_owned(),
                notes_path,
                above_threshold: false,
            }
        });
    let result = update(&mut state);
    let bytes = serde_json::to_vec(&state).ok()?;
    let nonce = NEXT_TEMP.fetch_add(1, Ordering::Relaxed);
    let temp_path = state_path.with_extension(format!("{}-{nonce}.tmp", std::process::id()));
    let mut temp = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temp_path)
        .ok()?;
    temp.write_all(&bytes).ok()?;
    temp.sync_all().ok()?;
    fs::rename(&temp_path, &state_path).ok()?;
    Some(result)
}

/// Reserve and persist this session's stable session-notes path.
pub fn reserve_session(harness: &str, session_id: &str) -> Option<PathBuf> {
    validate_session_id(session_id)?;
    with_state(harness, session_id, |state| state.notes_path.clone())
}

/// The configured threshold, or by default 250k tokens capped at 90% of the
/// model's context window when the harness reports one.
fn notes_threshold(config: &Config, window: Option<u64>) -> (u64, bool) {
    let default = window.map_or(DEFAULT_NOTES_AT_TOKENS, |window| {
        DEFAULT_NOTES_AT_TOKENS.min(window / 10 * 9).max(1)
    });
    let session = config
        .unknown
        .get("session")
        .and_then(toml::Value::as_table);
    let new_threshold = session.and_then(|session| session.get("notes_at_tokens"));
    let deprecated = new_threshold.is_none()
        && session.is_some_and(|session| session.contains_key("handoff_at_tokens"));
    let threshold =
        new_threshold.or_else(|| session.and_then(|session| session.get("handoff_at_tokens")));
    match threshold {
        None => (default, false),
        Some(value) => match value.as_integer().filter(|tokens| *tokens >= 0) {
            Some(tokens) => (tokens as u64, deprecated),
            None => {
                let key = if deprecated {
                    "handoff_at_tokens"
                } else {
                    "notes_at_tokens"
                };
                eprintln!("varde hook: invalid [session].{key}; using {default}");
                (default, deprecated)
            }
        },
    }
}

fn harness_kind(harness: &str) -> Option<ContextUsageHarness> {
    match harness {
        "claude" => Some(ContextUsageHarness::Claude),
        "codex" => Some(ContextUsageHarness::Codex),
        "opencode" => Some(ContextUsageHarness::Opencode),
        "pi" => Some(ContextUsageHarness::Pi),
        _ => None,
    }
}

/// Return agent-visible context for the first upward crossing, if any.
pub fn nudge(harness: &str, session_id: &str, payload: &[u8], config: &Config) -> Option<String> {
    validate_session_id(session_id)?;
    let value: Value = serde_json::from_slice(payload).ok()?;
    let session_file = [
        "transcript_path",
        "session_file",
        "sessionFile",
        "session_path",
    ]
    .iter()
    .find_map(|key| value.get(*key).and_then(Value::as_str))
    .map(Path::new);
    let direct = value.get("context_usage").unwrap_or(&value);
    let sample = context_usage(harness_kind(harness)?, session_file, Some(direct))?;
    let tokens = sample.current_tokens;
    let (threshold, deprecated_threshold) = notes_threshold(config, sample.context_window);
    if threshold == 0 {
        return None;
    }
    let path = with_state(harness, session_id, |state| {
        let above = tokens >= threshold;
        let fire = above && !state.above_threshold;
        state.above_threshold = above;
        fire.then(|| state.notes_path.clone())
    })??;
    if deprecated_threshold {
        eprintln!(
            "varde hook: [session].handoff_at_tokens is deprecated; use [session].notes_at_tokens"
        );
    }
    Some(format!(
        "Context reached {tokens} tokens (threshold {threshold}). Create or refresh the session note at {} and advise the user to compact.",
        path.display()
    ))
}
