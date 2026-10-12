//! Append-only friction event log.
//!
//! `friction.jsonl` is the source of truth for friction data; the SQLite store
//! is a cache rebuilt from it. This module owns the on-disk line format, the
//! append and replay IO, and the pure fold that turns events into item state.
//! It is storage-agnostic: callers hold the exclusive `fs2` lock on the handle
//! they pass to [`append`].

use std::collections::{HashMap, HashSet};
use std::fs::{self, File, OpenOptions};
use std::io::{ErrorKind, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use time::OffsetDateTime;

use crate::{FrictionIncidentProvenance, FrictionStatus, LearnError};

/// Log file name inside a store directory.
pub const LOG_FILE_NAME: &str = "friction.jsonl";

/// Event format version written by this build.
pub const FORMAT_VERSION: u32 = 1;

/// Number of hex characters kept from the event id digest.
const ID_HEX_LENGTH: usize = 16;

/// Git ignore rules written beside the log so `learn.db*` never enters Git.
const GITIGNORE_CONTENTS: &str = "learn.db*\nlearn.db.init.lock\n";

/// The union merge rule that lets two branches concatenate log lines.
const GITATTRIBUTES_LINE: &str = "friction.jsonl merge=union";

/// An event kind stored in the `kind` field.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EventKind {
    ItemAdded,
    OccurrenceAppended,
    StatusChanged,
    AdoptionRecorded,
}

impl EventKind {
    /// Stable wire name, matching the serde representation.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::ItemAdded => "item_added",
            Self::OccurrenceAppended => "occurrence_appended",
            Self::StatusChanged => "status_changed",
            Self::AdoptionRecorded => "adoption_recorded",
        }
    }
}

/// Body of an `item_added` event. The slug is derived by [`fold`], never stored.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ItemAdded {
    pub title: String,
    pub source: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub repo_root: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target: Option<String>,
}

/// Body of an `occurrence_appended` event, referencing its item by event id.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OccurrenceAppended {
    pub item: String,
    pub at: String,
    pub cwd: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub repo_root: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub head_sha: Option<String>,
    pub evidence: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cost: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub provenance: Option<FrictionIncidentProvenance>,
}

/// Body of a `status_changed` event, referencing its item by event id.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StatusChanged {
    pub item: String,
    pub at: String,
    pub from: String,
    pub to: String,
    pub reason: String,
}

/// Body of an `adoption_recorded` event, referencing items by event id.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AdoptionRecorded {
    pub at: String,
    pub summary: String,
    pub files: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub commit_sha: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub eval_before: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub eval_after: Option<String>,
    pub items: Vec<String>,
}

/// Typed event body. Serializes as the body object alone; the kind travels in
/// the sibling `kind` field of [`Event`].
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum EventBody {
    ItemAdded(ItemAdded),
    OccurrenceAppended(Box<OccurrenceAppended>),
    StatusChanged(StatusChanged),
    AdoptionRecorded(AdoptionRecorded),
}

impl EventBody {
    /// The kind this body belongs to.
    pub const fn kind(&self) -> EventKind {
        match self {
            Self::ItemAdded(_) => EventKind::ItemAdded,
            Self::OccurrenceAppended(_) => EventKind::OccurrenceAppended,
            Self::StatusChanged(_) => EventKind::StatusChanged,
            Self::AdoptionRecorded(_) => EventKind::AdoptionRecorded,
        }
    }
}

impl From<ItemAdded> for EventBody {
    fn from(body: ItemAdded) -> Self {
        Self::ItemAdded(body)
    }
}

impl From<OccurrenceAppended> for EventBody {
    fn from(body: OccurrenceAppended) -> Self {
        Self::OccurrenceAppended(Box::new(body))
    }
}

impl From<StatusChanged> for EventBody {
    fn from(body: StatusChanged) -> Self {
        Self::StatusChanged(body)
    }
}

impl From<AdoptionRecorded> for EventBody {
    fn from(body: AdoptionRecorded) -> Self {
        Self::AdoptionRecorded(body)
    }
}

/// One line of `friction.jsonl`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Event {
    pub v: u32,
    pub id: String,
    pub ts: String,
    pub kind: EventKind,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub repo: Option<String>,
    pub body: EventBody,
    #[serde(default, skip_serializing_if = "is_zero")]
    pub redacted: usize,
}

fn is_zero(value: &usize) -> bool {
    *value == 0
}

impl Event {
    /// Stamp an event with the current UTC time and a fresh id.
    pub fn new(repo: Option<String>, body: impl Into<EventBody>) -> Self {
        Self::at(now_timestamp(), repo, body)
    }

    /// Stamp an event with an explicit timestamp; used by imports and tests.
    pub fn at(ts: impl Into<String>, repo: Option<String>, body: impl Into<EventBody>) -> Self {
        let ts = ts.into();
        let body = body.into();
        let kind = body.kind();
        let id = event_id(&ts, kind, &body);
        Self {
            v: FORMAT_VERSION,
            id,
            ts,
            kind,
            repo,
            body,
            redacted: 0,
        }
    }

    /// Check the version, id, kind/body agreement, and status names.
    pub fn validate(&self) -> Result<(), String> {
        if self.v != FORMAT_VERSION {
            return Err(format!(
                "unsupported friction log version {} (expected {FORMAT_VERSION})",
                self.v
            ));
        }
        if self.id.len() != ID_HEX_LENGTH || !self.id.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err(format!("invalid friction event id `{}`", self.id));
        }
        if self.kind != self.body.kind() {
            return Err(format!(
                "kind `{}` does not match its body",
                self.kind.as_str()
            ));
        }
        if let EventBody::StatusChanged(body) = &self.body {
            for value in [&body.from, &body.to] {
                if FrictionStatus::parse(value).is_none() {
                    return Err(format!("unknown friction status `{value}`"));
                }
            }
        }
        Ok(())
    }
}

/// Events and the torn fragment a replay discarded.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct LogReplay {
    pub events: Vec<Event>,
    /// Final line without a trailing newline; incomplete, so never parsed.
    pub torn_line: Option<String>,
}

/// An item rebuilt from `item_added` and later `status_changed` events.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LogItem {
    /// The `item_added` event id other events reference.
    pub event_id: String,
    pub slug: String,
    pub title: String,
    pub source: String,
    pub repo_root: Option<String>,
    pub target: Option<String>,
    pub status: String,
    pub created_at: String,
}

/// An occurrence rebuilt from an `occurrence_appended` event.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LogOccurrence {
    pub event_id: String,
    pub item_event_id: String,
    pub at: String,
    pub cwd: String,
    pub repo_root: Option<String>,
    pub head_sha: Option<String>,
    pub evidence: String,
    pub cost: Option<String>,
    pub provenance: Option<FrictionIncidentProvenance>,
}

/// A transition rebuilt from a `status_changed` event.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LogStatusChange {
    pub event_id: String,
    pub item_event_id: String,
    pub at: String,
    pub from: String,
    pub to: String,
    pub reason: String,
}

/// An adoption rebuilt from an `adoption_recorded` event.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LogAdoption {
    pub event_id: String,
    pub at: String,
    pub summary: String,
    pub files: Vec<String>,
    pub commit_sha: Option<String>,
    pub eval_before: Option<String>,
    pub eval_after: Option<String>,
    pub item_event_ids: Vec<String>,
}

/// State rebuilt from a set of events.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct LogState {
    pub items: Vec<LogItem>,
    pub occurrences: Vec<LogOccurrence>,
    pub status_changes: Vec<LogStatusChange>,
    pub adoptions: Vec<LogAdoption>,
    /// Events dropped because they referenced an item event id that is absent.
    pub orphaned_events: usize,
}

/// Path of the friction log inside a store directory.
pub fn log_path(dir: &Path) -> PathBuf {
    dir.join(LOG_FILE_NAME)
}

/// Open (creating when absent) the log for reading and writing.
///
/// The caller takes the exclusive `fs2` lock before calling [`append`].
pub fn open_log(dir: &Path) -> Result<File, LearnError> {
    fs::create_dir_all(dir).map_err(|source| LearnError::StoreIo {
        operation: "create friction log directory",
        path: dir.to_path_buf(),
        source,
    })?;
    let path = log_path(dir);
    OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(&path)
        .map_err(|source| LearnError::StoreIo {
            operation: "open friction log",
            path,
            source,
        })
}

/// Append one event line, repairing a torn tail first.
///
/// `handle` must be opened read/write and locked exclusively by the caller.
/// When the file does not end in a newline the incomplete tail is truncated to
/// the last newline, so a partially written line never becomes permanent.
pub fn append(dir: &Path, handle: &mut File, event: &Event) -> Result<(), LearnError> {
    ensure_git_files(dir)?;
    repair_torn_tail(dir, handle)?;
    let mut body =
        serde_json::to_value(&event.body).map_err(|source| LearnError::StoreInvalid {
            message: format!("could not serialize friction event body: {source}"),
        })?;
    let redacted = redact_json_strings(&mut body);
    let body: EventBody =
        serde_json::from_value(body).map_err(|source| LearnError::StoreInvalid {
            message: format!("could not deserialize redacted friction event body: {source}"),
        })?;
    let mut persisted = event.clone();
    persisted.body = body;
    persisted.redacted += redacted;
    let line = serde_json::to_string(&persisted).map_err(|source| LearnError::StoreInvalid {
        message: format!("could not serialize friction event: {source}"),
    })?;
    let path = log_path(dir);
    handle
        .seek(SeekFrom::End(0))
        .and_then(|_| handle.write_all(line.as_bytes()))
        .and_then(|_| handle.write_all(b"\n"))
        .and_then(|_| handle.flush())
        .map_err(|source| LearnError::StoreIo {
            operation: "append friction log",
            path,
            source,
        })
}

fn redact_json_strings(value: &mut serde_json::Value) -> usize {
    match value {
        serde_json::Value::String(text) => {
            let result = crate::redact::apply(text);
            *text = result.text;
            result.count
        }
        serde_json::Value::Array(values) => values.iter_mut().map(redact_json_strings).sum(),
        serde_json::Value::Object(values) => values.values_mut().map(redact_json_strings).sum(),
        _ => 0,
    }
}

/// Read every complete event line, reporting a torn last line when present.
pub fn replay(dir: &Path) -> Result<LogReplay, LearnError> {
    let path = log_path(dir);
    let text = match fs::read_to_string(&path) {
        Ok(text) => text,
        Err(source) if source.kind() == ErrorKind::NotFound => return Ok(LogReplay::default()),
        Err(source) => {
            return Err(LearnError::StoreIo {
                operation: "read friction log",
                path,
                source,
            });
        }
    };
    let (body, torn_line) = split_torn_tail(&text);
    let mut events = Vec::new();
    for (index, line) in body.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let event: Event =
            serde_json::from_str(line).map_err(|source| LearnError::StoreInvalid {
                message: format!("invalid friction log line {}: {source}", index + 1),
            })?;
        event
            .validate()
            .map_err(|message| LearnError::StoreInvalid {
                message: format!("invalid friction log line {}: {message}", index + 1),
            })?;
        events.push(event);
    }
    Ok(LogReplay { events, torn_line })
}

/// Fold events into item state.
///
/// Events are ordered by `(ts, id)`, not file order, and duplicate ids are
/// dropped, so a union Git merge of two logs folds the same state. Slugs come
/// from the title; a colliding later item gets a deterministic `-N` suffix.
pub fn fold(events: impl IntoIterator<Item = Event>) -> LogState {
    let mut ordered: Vec<Event> = events.into_iter().collect();
    ordered.sort_by(|left, right| left.ts.cmp(&right.ts).then_with(|| left.id.cmp(&right.id)));
    let mut seen = HashSet::with_capacity(ordered.len());
    ordered.retain(|event| seen.insert(event.id.clone()));

    let mut state = LogState::default();
    let mut taken_slugs = HashSet::new();
    let mut pending_occurrences = Vec::new();
    let mut pending_status = Vec::new();
    let mut pending_adoptions = Vec::new();

    for event in ordered {
        match event.body {
            EventBody::ItemAdded(body) => {
                let slug = unique_slug(&taken_slugs, &safe_slug(&body.title));
                taken_slugs.insert(slug.clone());
                state.items.push(LogItem {
                    event_id: event.id,
                    slug,
                    title: body.title,
                    source: body.source,
                    repo_root: body.repo_root,
                    target: body.target,
                    status: FrictionStatus::Open.as_str().to_owned(),
                    created_at: event.ts,
                });
            }
            EventBody::OccurrenceAppended(body) => pending_occurrences.push(LogOccurrence {
                event_id: event.id,
                item_event_id: body.item,
                at: body.at,
                cwd: body.cwd,
                repo_root: body.repo_root,
                head_sha: body.head_sha,
                evidence: body.evidence,
                cost: body.cost,
                provenance: body.provenance,
            }),
            EventBody::StatusChanged(body) => pending_status.push(LogStatusChange {
                event_id: event.id,
                item_event_id: body.item,
                at: body.at,
                from: body.from,
                to: body.to,
                reason: body.reason,
            }),
            EventBody::AdoptionRecorded(body) => pending_adoptions.push(LogAdoption {
                event_id: event.id,
                at: body.at,
                summary: body.summary,
                files: body.files,
                commit_sha: body.commit_sha,
                eval_before: body.eval_before,
                eval_after: body.eval_after,
                item_event_ids: body.items,
            }),
        }
    }

    let index: HashMap<String, usize> = state
        .items
        .iter()
        .enumerate()
        .map(|(position, item)| (item.event_id.clone(), position))
        .collect();

    for change in pending_status {
        match index.get(change.item_event_id.as_str()) {
            Some(&position) => {
                state.items[position].status = change.to.clone();
                state.status_changes.push(change);
            }
            None => state.orphaned_events += 1,
        }
    }
    for occurrence in pending_occurrences {
        if index.contains_key(occurrence.item_event_id.as_str()) {
            state.occurrences.push(occurrence);
        } else {
            state.orphaned_events += 1;
        }
    }
    for adoption in pending_adoptions {
        if adoption
            .item_event_ids
            .iter()
            .all(|item| index.contains_key(item.as_str()))
        {
            state.adoptions.push(adoption);
        } else {
            state.orphaned_events += 1;
        }
    }

    state
}

/// A short digest of `(ts, pid, per-process counter, kind, body)`.
fn event_id(ts: &str, kind: EventKind, body: &EventBody) -> String {
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let counter = COUNTER.fetch_add(1, Ordering::Relaxed);
    let body = serde_json::to_string(body).expect("friction event body serializes");
    let material = format!(
        "{ts}\n{}\n{counter}\n{}\n{body}",
        std::process::id(),
        kind.as_str()
    );
    let digest = Sha256::digest(material.as_bytes());
    let mut id = String::with_capacity(ID_HEX_LENGTH);
    for byte in digest.iter().take(ID_HEX_LENGTH / 2) {
        id.push_str(&format!("{byte:02x}"));
    }
    id
}

/// Current UTC time in the store's fixed-width millisecond format.
pub(crate) fn now_timestamp() -> String {
    let since_epoch = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    format_timestamp(since_epoch.as_secs() as i64, since_epoch.subsec_millis())
}

/// Fixed-width RFC 3339 so lexicographic order matches chronological order.
fn format_timestamp(seconds: i64, millis: u32) -> String {
    let Ok(instant) = OffsetDateTime::from_unix_timestamp(seconds) else {
        return "1970-01-01T00:00:00.000Z".to_owned();
    };
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:03}Z",
        instant.year(),
        u8::from(instant.month()),
        instant.day(),
        instant.hour(),
        instant.minute(),
        instant.second(),
        millis,
    )
}

/// Split a possibly torn final line off the file contents.
pub(crate) fn split_torn_tail(text: &str) -> (&str, Option<String>) {
    if text.is_empty() || text.ends_with('\n') {
        return (text, None);
    }
    let start = text.rfind('\n').map_or(0, |index| index + 1);
    (&text[..start], Some(text[start..].to_owned()))
}

/// Truncate an unterminated final line, leaving the handle at the end.
fn repair_torn_tail(dir: &Path, handle: &mut File) -> Result<(), LearnError> {
    let path = log_path(dir);
    let io = |source| LearnError::StoreIo {
        operation: "append friction log",
        path: path.clone(),
        source,
    };
    let length = handle.metadata().map_err(io)?.len();
    if length == 0 {
        return Ok(());
    }
    handle.seek(SeekFrom::End(-1)).map_err(io)?;
    let mut last = [0_u8; 1];
    handle.read_exact(&mut last).map_err(io)?;
    if last[0] == b'\n' {
        handle.seek(SeekFrom::End(0)).map_err(io)?;
        return Ok(());
    }

    const CHUNK: u64 = 8 * 1024;
    let mut position = length;
    let mut newline = None;
    while position > 0 {
        let start = position.saturating_sub(CHUNK);
        let size = (position - start) as usize;
        let mut buffer = vec![0_u8; size];
        handle.seek(SeekFrom::Start(start)).map_err(io)?;
        handle.read_exact(&mut buffer).map_err(io)?;
        if let Some(offset) = buffer.iter().rposition(|byte| *byte == b'\n') {
            newline = Some(start + offset as u64);
            break;
        }
        position = start;
    }

    let keep = newline.map_or(0, |offset| offset + 1);
    handle.set_len(keep).map_err(io)?;
    handle.seek(SeekFrom::End(0)).map_err(io)?;
    Ok(())
}

/// Write the Git ignore rules and union merge rule when they are missing.
pub(crate) fn ensure_git_files(dir: &Path) -> Result<(), LearnError> {
    let gitignore = dir.join(".gitignore");
    if !gitignore.exists() {
        fs::write(&gitignore, GITIGNORE_CONTENTS).map_err(|source| LearnError::StoreIo {
            operation: "write friction log .gitignore",
            path: gitignore,
            source,
        })?;
    }

    let gitattributes = dir.join(".gitattributes");
    let existing = match fs::read_to_string(&gitattributes) {
        Ok(text) => text,
        Err(source) if source.kind() == ErrorKind::NotFound => String::new(),
        Err(source) => {
            return Err(LearnError::StoreIo {
                operation: "read friction log .gitattributes",
                path: gitattributes,
                source,
            });
        }
    };
    if existing
        .lines()
        .any(|line| line.trim() == GITATTRIBUTES_LINE)
    {
        return Ok(());
    }
    let mut updated = existing;
    if !updated.is_empty() && !updated.ends_with('\n') {
        updated.push('\n');
    }
    updated.push_str(GITATTRIBUTES_LINE);
    updated.push('\n');
    fs::write(&gitattributes, updated).map_err(|source| LearnError::StoreIo {
        operation: "write friction log .gitattributes",
        path: gitattributes,
        source,
    })
}

/// Lowercase, hyphenated slug derived from a title.
pub(crate) fn safe_slug(title: &str) -> String {
    let mut slug = String::new();
    let mut separator = false;
    for character in title.chars() {
        if character.is_ascii_alphanumeric() {
            if separator && !slug.is_empty() {
                slug.push('-');
            }
            slug.push(character.to_ascii_lowercase());
            separator = false;
        } else {
            separator = true;
        }
        if slug.len() >= 80 {
            break;
        }
    }
    while slug.ends_with('-') {
        slug.pop();
    }
    if slug.is_empty() {
        "friction".to_owned()
    } else if slug.bytes().all(|byte| byte.is_ascii_digit()) {
        format!("friction-{slug}")
    } else {
        slug
    }
}

/// Lowest free `base`, `base-2`, `base-3`, ... slug.
pub(crate) fn unique_slug(taken: &HashSet<String>, base: &str) -> String {
    if !taken.contains(base) {
        return base.to_owned();
    }
    let mut suffix = 2_u64;
    loop {
        let candidate = format!("{base}-{suffix}");
        if !taken.contains(&candidate) {
            return candidate;
        }
        suffix = suffix.saturating_add(1);
    }
}

#[cfg(test)]
mod tests {
    use std::fs::OpenOptions;
    use std::io::Write;

    use tempfile::tempdir;

    use super::*;

    fn item(title: &str) -> EventBody {
        ItemAdded {
            title: title.to_owned(),
            source: "session".to_owned(),
            repo_root: None,
            target: None,
        }
        .into()
    }

    fn occurrence(item_event_id: &str) -> EventBody {
        OccurrenceAppended {
            item: item_event_id.to_owned(),
            at: "2026-01-01T00:00:00.000Z".to_owned(),
            cwd: "/work".to_owned(),
            repo_root: None,
            head_sha: None,
            evidence: "saw it again".to_owned(),
            cost: None,
            provenance: None,
        }
        .into()
    }

    fn status(item_event_id: &str, from: &str, to: &str) -> EventBody {
        StatusChanged {
            item: item_event_id.to_owned(),
            at: "2026-01-01T00:00:00.000Z".to_owned(),
            from: from.to_owned(),
            to: to.to_owned(),
            reason: "fixed".to_owned(),
        }
        .into()
    }

    #[test]
    fn append_writes_lines_and_bootstraps_git_files() {
        let dir = tempdir().expect("temp dir");
        let mut handle = open_log(dir.path()).expect("open log");
        let first = Event::at("2026-01-01T00:00:00.000Z", None, item("Alpha friction"));
        let second = Event::at("2026-01-01T00:00:01.000Z", None, occurrence(&first.id));
        append(dir.path(), &mut handle, &first).expect("append first");
        append(dir.path(), &mut handle, &second).expect("append second");

        let text = fs::read_to_string(log_path(dir.path())).expect("read log");
        assert!(text.ends_with('\n'), "log ends with a newline: {text:?}");
        assert_eq!(text.lines().count(), 2, "one line per event");

        let wire: serde_json::Value =
            serde_json::from_str(text.lines().next().expect("first line")).expect("json line");
        assert_eq!(wire["v"], serde_json::json!(FORMAT_VERSION));
        assert_eq!(wire["kind"], serde_json::json!("item_added"));
        assert_eq!(wire["id"], serde_json::json!(first.id));
        assert_eq!(wire["ts"], serde_json::json!(first.ts));
        assert_eq!(wire["body"]["title"], serde_json::json!("Alpha friction"));
        assert!(
            wire.get("repo").is_none(),
            "absent optional repo is omitted"
        );

        let replayed = replay(dir.path()).expect("replay");
        assert_eq!(replayed.events, vec![first, second]);
        assert_eq!(replayed.torn_line, None);

        let gitignore = fs::read_to_string(dir.path().join(".gitignore")).expect("gitignore");
        assert!(gitignore.contains("learn.db*"));
        assert!(gitignore.contains("learn.db.init.lock"));
        let gitattributes =
            fs::read_to_string(dir.path().join(".gitattributes")).expect("gitattributes");
        assert!(gitattributes.lines().any(|line| line == GITATTRIBUTES_LINE));
    }

    #[test]
    fn append_truncates_a_torn_line_before_writing() {
        let dir = tempdir().expect("temp dir");
        let mut handle = open_log(dir.path()).expect("open log");
        let first = Event::at("2026-01-01T00:00:00.000Z", None, item("Alpha"));
        append(dir.path(), &mut handle, &first).expect("append first");

        let mut raw = OpenOptions::new()
            .append(true)
            .open(log_path(dir.path()))
            .expect("open for partial write");
        raw.write_all(br#"{"v":1,"id":"deadbeef""#)
            .expect("write torn fragment");
        raw.flush().expect("flush torn fragment");
        drop(raw);

        let second = Event::at("2026-01-01T00:00:01.000Z", None, item("Beta"));
        append(dir.path(), &mut handle, &second).expect("append second");

        let text = fs::read_to_string(log_path(dir.path())).expect("read log");
        assert!(
            !text.contains("deadbeef"),
            "torn fragment removed: {text:?}"
        );
        assert_eq!(text.lines().count(), 2);
        let replayed = replay(dir.path()).expect("replay");
        assert_eq!(replayed.events, vec![first, second]);
        assert_eq!(replayed.torn_line, None);
    }

    #[test]
    fn replay_skips_and_reports_a_torn_last_line() {
        let dir = tempdir().expect("temp dir");
        let mut handle = open_log(dir.path()).expect("open log");
        let complete = Event::at("2026-01-01T00:00:00.000Z", None, item("Alpha"));
        append(dir.path(), &mut handle, &complete).expect("append complete");

        let mut raw = OpenOptions::new()
            .append(true)
            .open(log_path(dir.path()))
            .expect("open for partial write");
        raw.write_all(b"torn fragment").expect("write fragment");
        raw.flush().expect("flush fragment");
        drop(raw);

        let replayed = replay(dir.path()).expect("replay");
        assert_eq!(replayed.events, vec![complete]);
        assert_eq!(replayed.torn_line.as_deref(), Some("torn fragment"));
    }

    #[test]
    fn fold_drops_duplicate_event_ids() {
        let adding = Event::at("2026-01-01T00:00:00.000Z", None, item("Alpha"));
        let occurrence_event = Event::at("2026-01-01T00:00:01.000Z", None, occurrence(&adding.id));
        let state = fold(vec![
            adding.clone(),
            occurrence_event.clone(),
            adding,
            occurrence_event,
        ]);
        assert_eq!(state.items.len(), 1);
        assert_eq!(state.occurrences.len(), 1);
        assert_eq!(state.orphaned_events, 0);
    }

    #[test]
    fn fold_is_order_independent_for_a_log_union() {
        let alpha = Event::at("2026-01-01T00:00:00.000Z", None, item("Alpha"));
        let alpha_occurrence = Event::at("2026-01-01T00:00:02.000Z", None, occurrence(&alpha.id));
        let beta = Event::at("2026-01-01T00:00:01.000Z", None, item("Beta"));
        let beta_status = Event::at(
            "2026-01-01T00:00:03.000Z",
            None,
            status(&beta.id, "open", "resolved"),
        );

        let forward = fold(vec![
            alpha.clone(),
            alpha_occurrence.clone(),
            beta.clone(),
            beta_status.clone(),
        ]);
        let reverse = fold(vec![beta_status, beta, alpha_occurrence, alpha]);

        assert_eq!(forward, reverse, "union order must not change fold state");
        assert_eq!(forward.items.len(), 2);
        assert_eq!(forward.occurrences.len(), 1);
        assert_eq!(forward.status_changes.len(), 1);
        assert_eq!(forward.items[1].status, "resolved");
    }

    #[test]
    fn fold_suffixes_a_colliding_slug_deterministically() {
        let first = Event::at("2026-01-01T00:00:00.000Z", None, item("Same title"));
        let second = Event::at("2026-01-01T00:00:01.000Z", None, item("Same title"));

        let forward = fold(vec![first.clone(), second.clone()]);
        let reverse = fold(vec![second, first]);

        let slugs: Vec<&str> = forward
            .items
            .iter()
            .map(|item| item.slug.as_str())
            .collect();
        assert_eq!(slugs, vec!["same-title", "same-title-2"]);
        assert_eq!(forward.items, reverse.items, "suffix follows fold order");
    }
}
