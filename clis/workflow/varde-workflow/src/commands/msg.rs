//! Append one-line messages to a per-machine inbox and read them back.
//!
//! One append-only JSON-lines store under `<working>/.cache/inbox/messages.jsonl`
//! and one byte-offset cursor per reader under `<working>/.cache/inbox/cursors/`.
//! `send` appends one encoded line (capped so the write stays atomic); `read`
//! prints a reader's unread messages and advances its cursor, while `--all`
//! prints every message without touching a cursor.

use crate::cli::{MsgArgs, MsgCommand, ReadArgs, SendArgs};
use crate::output::print_success;
use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use varde_workflow_core::memory::MemoryPaths;

/// Longest accepted message text, in characters.
pub const MAX_TEXT_CHARS: usize = 300;
/// Longest appended line, in bytes. Keeping it small keeps one append atomic.
pub const MAX_LINE_BYTES: usize = 1_000;

const KINDS: [&str; 6] = [
    "blocked",
    "needs-user",
    "done",
    "info",
    "stale",
    "merge-ready",
];

/// One stored inbox message.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    pub ts: String,
    pub from: String,
    pub to: String,
    pub kind: String,
    pub text: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub notes: Option<String>,
}

impl Message {
    /// The one-line form printed by `read` and injected by the hook.
    pub fn line(&self) -> String {
        match &self.notes {
            Some(notes) => format!(
                "{} {}: {} (notes: {})",
                self.from, self.kind, self.text, notes
            ),
            None => format!("{} {}: {}", self.from, self.kind, self.text),
        }
    }
}

pub fn run(args: MsgArgs) -> Result<()> {
    match args.command {
        MsgCommand::Send(args) => send(args),
        MsgCommand::Read(args) => read(args),
    }
}

fn send(args: SendArgs) -> Result<()> {
    append_message(
        &args.from,
        &args.to,
        &args.kind,
        &args.text,
        args.notes.as_deref(),
    )
}

/// Append a message to the inbox for the current working store.
pub fn append_message(
    from: &str,
    to: &str,
    kind: &str,
    text: &str,
    notes: Option<&Path>,
) -> Result<()> {
    validate_address("--from", from)?;
    validate_address("--to", to)?;
    if !KINDS.contains(&kind) {
        bail!(
            "unknown message kind `{}`; allowed kinds are {}",
            kind,
            KINDS.join(", ")
        );
    }
    validate_text(text)?;
    append_message_inner(from, to, kind, text, notes, None, false)
}

/// Append watch event text after removing controls and respecting the encoded
/// inbox line limit. User initiated `msg send` remains strict via append_message.
pub fn append_event_message(
    working: &Path,
    from: &str,
    to: &str,
    kind: &str,
    text: &str,
    notes: Option<&Path>,
) -> Result<()> {
    append_message_inner(
        from,
        to,
        kind,
        &sanitize_text(text),
        notes,
        Some(working),
        true,
    )
}

fn append_message_inner(
    from: &str,
    to: &str,
    kind: &str,
    text: &str,
    notes: Option<&Path>,
    working: Option<&Path>,
    shrink_to_fit: bool,
) -> Result<()> {
    validate_address("--from", from)?;
    validate_address("--to", to)?;
    if !KINDS.contains(&kind) {
        bail!(
            "unknown message kind `{}`; allowed kinds are {}",
            kind,
            KINDS.join(", ")
        );
    }
    let message = Message {
        ts: rfc3339_utc(SystemTime::now()),
        from: from.to_owned(),
        to: to.to_owned(),
        kind: kind.to_owned(),
        text: text.to_owned(),
        notes: notes.map(|path| path.to_string_lossy().into_owned()),
    };
    let mut message = message;
    let mut encoded = serde_json::to_string(&message).context("could not encode the message")?;
    if !shrink_to_fit && encoded.len() + 1 > MAX_LINE_BYTES {
        bail!(line_limit_message(encoded.len() + 1));
    }
    while encoded.len() + 1 > MAX_LINE_BYTES && !message.text.is_empty() {
        message.text.pop();
        if !message.text.is_empty() {
            message.text.pop();
            message.text.push('…');
        }
        encoded = serde_json::to_string(&message).context("could not encode the message")?;
    }
    let line = format!("{encoded}\n");
    let owned_working;
    let working = match working {
        Some(working) => working,
        None => {
            owned_working = working_dir()?;
            &owned_working
        }
    };
    append_line(&store_path(working), line.as_bytes())
}

fn sanitize_text(text: &str) -> String {
    let clean: String = text
        .chars()
        .filter(|character| !character.is_control())
        .collect();
    let mut characters = clean.chars();
    let prefix: String = characters.by_ref().take(MAX_TEXT_CHARS).collect();
    if characters.next().is_some() {
        let prefix: String = prefix.chars().take(MAX_TEXT_CHARS - 1).collect();
        format!("{prefix}…")
    } else {
        prefix
    }
}

fn read(args: ReadArgs) -> Result<()> {
    let working = working_dir()?;
    if args.all {
        return print_messages(&read_all(&working)?, args.json);
    }
    let (messages, commit) = read_unread(&working, &args.address)?;
    print_messages(&messages, args.json)?;
    if let Some(next) = commit {
        commit_cursor(&working, &args.address, next)?;
    }
    Ok(())
}

fn print_messages(messages: &[Message], json: bool) -> Result<()> {
    if json {
        return print_success(json!({ "messages": messages }));
    }
    let mut stdout = std::io::stdout().lock();
    for message in messages {
        writeln!(stdout, "{}", message.line())?;
    }
    Ok(())
}

/// Read every message in the store without touching any cursor.
pub fn read_all(working: &Path) -> Result<Vec<Message>> {
    let store = store_path(working);
    let bytes = match fs::read(&store) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => {
            return Err(error)
                .with_context(|| format!("could not read inbox store {}", store.display()));
        }
    };
    Ok(parse_complete(&bytes, 0).0)
}

/// Read `reader`'s unread messages without advancing its cursor. The returned
/// offset is for the caller to commit after the messages are delivered, so a
/// failed delivery leaves them unread.
pub fn read_unread(working: &Path, reader: &str) -> Result<(Vec<Message>, Option<u64>)> {
    validate_address("--as", reader)?;
    let store = store_path(working);
    let bytes = match fs::read(&store) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Ok((Vec::new(), None));
        }
        Err(error) => {
            return Err(error)
                .with_context(|| format!("could not read inbox store {}", store.display()));
        }
    };
    let cursor = read_cursor(working, reader)?;
    // A cursor past the end of the file resets to zero.
    let cursor = if cursor > bytes.len() as u64 {
        0
    } else {
        cursor
    };
    let (mut messages, next) = parse_complete(&bytes[cursor as usize..], cursor as usize);
    messages.retain(|message| message.to == reader);
    Ok((messages, (next != cursor).then_some(next)))
}

/// Advance `reader`'s cursor past delivered messages.
pub fn commit_cursor(working: &Path, reader: &str, offset: u64) -> Result<()> {
    write_cursor(working, reader, offset)
}

/// Parse the newline-terminated lines of `bytes`, returning the messages and
/// the absolute offset just past the last complete line. A torn final line
/// without a newline stays unread for the next call.
fn parse_complete(bytes: &[u8], base: usize) -> (Vec<Message>, u64) {
    let complete = match bytes.iter().rposition(|byte| *byte == b'\n') {
        Some(index) => index + 1,
        None => 0,
    };
    let mut messages = Vec::new();
    for line in bytes[..complete].split(|byte| *byte == b'\n') {
        if line.is_empty() {
            continue;
        }
        if let Ok(message) = serde_json::from_slice::<Message>(line) {
            messages.push(message);
        }
    }
    (messages, (base + complete) as u64)
}

fn working_dir() -> Result<PathBuf> {
    let cwd = std::env::current_dir().context("could not resolve current directory")?;
    let root = varde_workflow_core::memory::find_root(&cwd).unwrap_or(cwd);
    Ok(MemoryPaths::resolve(&root)?.working.path)
}

fn inbox_dir(working: &Path) -> PathBuf {
    working.join(".cache").join("inbox")
}

fn store_path(working: &Path) -> PathBuf {
    inbox_dir(working).join("messages.jsonl")
}

fn cursors_dir(working: &Path) -> PathBuf {
    inbox_dir(working).join("cursors")
}

fn append_line(path: &Path, bytes: &[u8]) -> Result<()> {
    let parent = path.parent().context("inbox store path has no parent")?;
    fs::create_dir_all(parent)
        .with_context(|| format!("could not create inbox store {}", parent.display()))?;
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .with_context(|| format!("could not open inbox store {}", path.display()))?;
    file.write_all(bytes)
        .with_context(|| format!("could not append to inbox store {}", path.display()))
}

fn read_cursor(working: &Path, reader: &str) -> Result<u64> {
    let path = cursors_dir(working).join(reader);
    match fs::read_to_string(&path) {
        Ok(text) => Ok(text.trim().parse().unwrap_or(0)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(0),
        Err(error) => {
            Err(error).with_context(|| format!("could not read inbox cursor {}", path.display()))
        }
    }
}

fn write_cursor(working: &Path, reader: &str, offset: u64) -> Result<()> {
    let dir = cursors_dir(working);
    fs::create_dir_all(&dir)
        .with_context(|| format!("could not create inbox cursor store {}", dir.display()))?;
    let path = dir.join(reader);
    let temporary = dir.join(format!(".{reader}.{}.tmp", std::process::id()));
    let result = (|| {
        let mut file = OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(&temporary)?;
        write!(file, "{offset}")?;
        file.sync_all()?;
        fs::rename(&temporary, &path)
    })();
    if let Err(error) = result {
        let _ = fs::remove_file(&temporary);
        return Err(error)
            .with_context(|| format!("could not store inbox cursor {}", path.display()));
    }
    Ok(())
}

fn validate_address(flag: &str, value: &str) -> Result<()> {
    if value.is_empty() {
        bail!("{flag} must not be empty");
    }
    if !value
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        bail!("{flag} `{value}` must be one word of letters, digits, `.`, `_` or `-`");
    }
    Ok(())
}

fn validate_text(text: &str) -> Result<()> {
    if text.is_empty() {
        bail!("message text must not be empty");
    }
    if text.contains(['\n', '\r']) {
        bail!("message text must be one line without newlines");
    }
    let chars = text.chars().count();
    if chars > MAX_TEXT_CHARS {
        bail!(
            "message text is {chars} characters; {MAX_TEXT_CHARS} characters is the limit and \
             the encoded line must also stay within {MAX_LINE_BYTES} bytes; use --notes <path>"
        );
    }
    Ok(())
}

fn line_limit_message(bytes: usize) -> String {
    format!(
        "message encodes to {bytes} bytes; the encoded line limit is {MAX_LINE_BYTES} bytes and \
         the text limit is {MAX_TEXT_CHARS} characters"
    )
}

/// Current UTC time as `YYYY-MM-DDTHH:MM:SSZ`.
fn rfc3339_utc(now: SystemTime) -> String {
    let seconds = now.duration_since(UNIX_EPOCH).unwrap_or_default().as_secs() as i64;
    let days = seconds.div_euclid(86_400);
    let day_seconds = seconds.rem_euclid(86_400);
    let (year, month, day) = civil_from_days(days);
    let hour = day_seconds / 3_600;
    let minute = (day_seconds % 3_600) / 60;
    let second = day_seconds % 60;
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
}

/// Days since the Unix epoch to a proleptic Gregorian date (Howard Hinnant's
/// `civil_from_days`).
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let shifted = days + 719_468;
    let era = if shifted >= 0 {
        shifted
    } else {
        shifted - 146_096
    } / 146_097;
    let day_of_era = (shifted - era * 146_097) as u64;
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let year = year_of_era as i64 + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_prime = (5 * day_of_year + 2) / 153;
    let day = (day_of_year - (153 * month_prime + 2) / 5 + 1) as u32;
    let month = if month_prime < 10 {
        month_prime + 3
    } else {
        month_prime - 9
    } as u32;
    (if month <= 2 { year + 1 } else { year }, month, day)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rfc3339_formats_a_known_instant() {
        assert_eq!(rfc3339_utc(UNIX_EPOCH), "1970-01-01T00:00:00Z");
        assert_eq!(
            rfc3339_utc(UNIX_EPOCH + std::time::Duration::from_secs(1_700_000_000)),
            "2023-11-14T22:13:20Z"
        );
    }

    #[test]
    fn sanitize_text_strips_controls_and_truncates_with_ellipsis() {
        assert_eq!(sanitize_text("a\u{1b}b\u{7f}c"), "abc");
        let sanitized = sanitize_text(&"x".repeat(MAX_TEXT_CHARS + 1));
        assert_eq!(sanitized.chars().count(), MAX_TEXT_CHARS);
        assert!(sanitized.ends_with('…'));
        assert_eq!(
            sanitized
                .chars()
                .take(MAX_TEXT_CHARS - 1)
                .collect::<String>(),
            "x".repeat(MAX_TEXT_CHARS - 1)
        );
    }

    #[test]
    fn event_kinds_are_allowed_message_kinds() {
        assert!(KINDS.contains(&"stale"));
        assert!(KINDS.contains(&"merge-ready"));
    }
}
