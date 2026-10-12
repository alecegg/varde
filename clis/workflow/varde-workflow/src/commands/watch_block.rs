//! Render and write the generated plan-status block in a session notes file.
//!
//! The block is delimited by [`BEGIN_MARKER`] and [`END_MARKER`]. A write
//! replaces only the text between the markers, appends the block when neither
//! marker is present, and creates a `status: draft` stub when the file is
//! missing. The block holds minimum state plus lookup commands, never elapsed
//! times, so repeated renders of equal state produce identical bytes.

use anyhow::{Context, Result};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

/// Opening marker of the generated block.
pub const BEGIN_MARKER: &str = "<!-- varde:plan-status:begin -->";
/// Closing marker of the generated block.
pub const END_MARKER: &str = "<!-- varde:plan-status:end -->";
/// Fixed lookup hints: the block stores what cannot be looked up, not a summary.
pub const LOOKUP_LINE: &str = "lookup: varde plan status | varde plan show <id> | \
varde learn friction list --status open | git -C <worktree> log";

/// Frontmatter written when watch has to create the notes file. `status:
/// draft` keeps it out of the resume list until the main agent writes to it.
const STUB: &[u8] = b"---\ntype: session-notes\nstatus: draft\n---\n";

/// How often a write is retried when the file changes under it.
const MAX_ATTEMPTS: usize = 8;

static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);

/// One watched plan's rendered state.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlanRow {
    /// Plan id.
    pub id: String,
    /// Classified state.
    pub state: PlanState,
    /// Tasks done.
    pub done: usize,
    /// Tasks total.
    pub total: usize,
    /// Blocked task count.
    pub blocked: usize,
    /// Live open-question count.
    pub open_questions: usize,
    /// The plan's now line, when it has one.
    pub now: Option<String>,
    /// The owner has not handed back since this plan became idle.
    pub idle_no_handback: bool,
}

/// The state shown in a plan row.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PlanState {
    /// Active with recent activity.
    Active,
    /// The plan itself is blocked.
    Blocked,
    /// Every task is done and the plan waits on the finish review.
    MergeReady,
    /// A live `waiting:` entry in the plan-now line marks the plan as waiting.
    Waiting,
    /// Terminal, still inside the finished window.
    Finished,
    /// Idle past the threshold; `since` is the HH:MM of the newest activity.
    Stale {
        /// Clock time of the newest activity, `HH:MM`.
        since: String,
    },
}

impl PlanState {
    fn label(&self) -> String {
        match self {
            PlanState::Active => "active".to_string(),
            PlanState::Blocked => "blocked".to_string(),
            PlanState::MergeReady => "merge-ready".to_string(),
            PlanState::Waiting => "waiting".to_string(),
            PlanState::Finished => "finished".to_string(),
            PlanState::Stale { since } => format!("stale since {since}"),
        }
    }
}

/// Everything the generated block renders.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct BlockModel {
    /// One row per watched plan; rendered sorted by id.
    pub rows: Vec<PlanRow>,
    /// Blocked tasks as `<plan>/<task>`; rendered sorted when non-empty.
    pub blocked_tasks: Vec<String>,
}

/// Render the block body, the text that goes between the markers.
pub fn render(model: &BlockModel) -> String {
    let mut rows = model.rows.clone();
    rows.sort_by(|left, right| left.id.cmp(&right.id));
    let mut lines: Vec<String> = rows.iter().map(render_row).collect();
    if !model.blocked_tasks.is_empty() {
        let mut tasks = model.blocked_tasks.clone();
        tasks.sort();
        if !lines.is_empty() {
            lines.push(String::new());
        }
        lines.push(format!("blocked tasks: {}", tasks.join(", ")));
    }
    if !lines.is_empty() {
        lines.push(String::new());
    }
    lines.push(LOOKUP_LINE.to_string());
    lines.join("\n")
}

fn render_row(row: &PlanRow) -> String {
    let mut line = format!(
        "{} [{}] {}/{}",
        row.id,
        row.state.label(),
        row.done,
        row.total
    );
    if row.blocked > 0 {
        line.push_str(&format!(", {} blocked", row.blocked));
    }
    if row.open_questions > 0 {
        line.push_str(&format!(" | q{}", row.open_questions));
    }
    if let Some(now) = row
        .now
        .as_deref()
        .map(str::trim)
        .filter(|now| !now.is_empty())
    {
        line.push_str(" | ");
        // A now line must never introduce a second marker pair: `merge`
        // counts markers textually, so a stray marker makes every later
        // write treat the block as malformed and leave it stale.
        line.push_str(&now.replace("<!--", "<!- -"));
    }
    if row.idle_no_handback {
        line.push_str(" | idle-no-handback");
    }
    line
}

enum Merge {
    Unchanged,
    Updated(Vec<u8>),
    Malformed { begins: usize, ends: usize },
}

/// Write `model` into the generated block of `path`.
///
/// Only the marked region changes; a file with no markers gets the block
/// appended, and a missing file is created as a `status: draft` stub. A file
/// with malformed markers is left alone with a warning on stderr. Equal bytes
/// are never written, so the file's mtime is stable across no-op refreshes.
pub fn write_block(path: &Path, model: &BlockModel) -> Result<()> {
    write_block_inner(path, model, &mut |_| {})
}

fn write_block_inner(
    path: &Path,
    model: &BlockModel,
    before_commit: &mut dyn FnMut(&Path),
) -> Result<()> {
    let target = resolve_target(path)?;
    for _ in 0..MAX_ATTEMPTS {
        let original = match fs::read(&target) {
            Ok(bytes) => Some(bytes),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
            Err(error) => {
                return Err(error)
                    .with_context(|| format!("could not read session notes {}", target.display()));
            }
        };
        let base = original.clone().unwrap_or_else(|| STUB.to_vec());
        let updated = match merge(&base, model) {
            Merge::Unchanged => return Ok(()),
            Merge::Malformed { begins, ends } => {
                eprintln!(
                    "varde plan watch: {} has {begins} begin and {ends} end markers; left unchanged",
                    target.display()
                );
                return Ok(());
            }
            Merge::Updated(bytes) => bytes,
        };
        let temporary = temp_path(&target)?;
        if let Err(error) = write_temp(&temporary, &updated) {
            let _ = fs::remove_file(&temporary);
            return Err(error)
                .with_context(|| format!("could not stage session notes {}", target.display()));
        }
        before_commit(&target);
        let current = match fs::read(&target) {
            Ok(bytes) => Some(bytes),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
            Err(error) => {
                let _ = fs::remove_file(&temporary);
                return Err(error).with_context(|| {
                    format!("could not re-read session notes {}", target.display())
                });
            }
        };
        // Re-read immediately before the rename: a concurrent writer must not
        // lose its change, so redo the merge over whatever is there now.
        if current != original {
            let _ = fs::remove_file(&temporary);
            continue;
        }
        if let Err(error) = fs::rename(&temporary, &target) {
            let _ = fs::remove_file(&temporary);
            return Err(error)
                .with_context(|| format!("could not replace session notes {}", target.display()));
        }
        return Ok(());
    }
    eprintln!(
        "varde plan watch: {} kept changing while writing; left unchanged",
        path.display()
    );
    Ok(())
}

fn merge(original: &[u8], model: &BlockModel) -> Merge {
    let block = render(model);
    let begins = count_matches(original, BEGIN_MARKER.as_bytes());
    let ends = count_matches(original, END_MARKER.as_bytes());
    if begins == 0 && ends == 0 {
        return Merge::Updated(append_block(original, &block));
    }
    if begins != 1 || ends != 1 {
        return Merge::Malformed { begins, ends };
    }
    let begin_at = find(original, BEGIN_MARKER.as_bytes()).expect("counted exactly one begin");
    let end_at = find(original, END_MARKER.as_bytes()).expect("counted exactly one end");
    let content_at = begin_at + BEGIN_MARKER.len();
    if content_at > end_at {
        return Merge::Malformed { begins, ends };
    }
    let mut updated = Vec::with_capacity(original.len() + block.len() + 2);
    updated.extend_from_slice(&original[..content_at]);
    updated.push(b'\n');
    updated.extend_from_slice(block.as_bytes());
    updated.push(b'\n');
    updated.extend_from_slice(&original[end_at..]);
    if updated == original {
        Merge::Unchanged
    } else {
        Merge::Updated(updated)
    }
}

fn append_block(original: &[u8], block: &str) -> Vec<u8> {
    let mut out = original.to_vec();
    if !out.is_empty() {
        if !out.ends_with(b"\n") {
            out.push(b'\n');
        }
        out.push(b'\n');
    }
    out.extend_from_slice(BEGIN_MARKER.as_bytes());
    out.push(b'\n');
    out.extend_from_slice(block.as_bytes());
    out.push(b'\n');
    out.extend_from_slice(END_MARKER.as_bytes());
    out.push(b'\n');
    out
}

fn find(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

fn count_matches(haystack: &[u8], needle: &[u8]) -> usize {
    haystack
        .windows(needle.len())
        .filter(|window| *window == needle)
        .count()
}

/// Resolve a symlinked path so the rename replaces the target, not the link,
/// and create the parent directory when the notes file does not exist yet.
fn resolve_target(path: &Path) -> Result<PathBuf> {
    if let Ok(resolved) = fs::canonicalize(path) {
        return Ok(resolved);
    }
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .context("session notes path has no parent directory")?;
    fs::create_dir_all(parent).with_context(|| {
        format!(
            "could not create session notes directory {}",
            parent.display()
        )
    })?;
    let parent = fs::canonicalize(parent).with_context(|| {
        format!(
            "could not resolve session notes directory {}",
            parent.display()
        )
    })?;
    let filename = path
        .file_name()
        .context("session notes path has no file name")?;
    Ok(parent.join(filename))
}

fn temp_path(target: &Path) -> Result<PathBuf> {
    let directory = target
        .parent()
        .context("session notes path has no parent")?;
    let filename = target
        .file_name()
        .and_then(|name| name.to_str())
        .context("session notes path has an invalid filename")?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let counter = TEMP_COUNTER.fetch_add(1, Ordering::Relaxed);
    Ok(directory.join(format!(
        ".{filename}.{}.{}.{}.tmp",
        std::process::id(),
        nonce,
        counter
    )))
}

fn write_temp(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::File;
    use std::os::unix::fs::symlink;
    use std::time::Duration;
    use varde_workflow_core::memory::NOTES_FILE;

    fn temp_dir(label: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "varde-watch-block-{label}-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&root).unwrap();
        root
    }

    fn row(id: &str, state: PlanState) -> PlanRow {
        PlanRow {
            id: id.to_string(),
            state,
            done: 1,
            total: 2,
            blocked: 0,
            open_questions: 0,
            now: None,
            idle_no_handback: false,
        }
    }

    fn model(id: &str, state: PlanState) -> BlockModel {
        BlockModel {
            rows: vec![row(id, state)],
            blocked_tasks: Vec::new(),
        }
    }

    fn outside_markers(bytes: &[u8]) -> (Vec<u8>, Vec<u8>) {
        let begin = find(bytes, BEGIN_MARKER.as_bytes()).unwrap() + BEGIN_MARKER.len();
        let end = find(bytes, END_MARKER.as_bytes()).unwrap();
        (bytes[..begin].to_vec(), bytes[end..].to_vec())
    }

    fn backdate(path: &Path, stamp: SystemTime) {
        File::options()
            .write(true)
            .open(path)
            .unwrap()
            .set_modified(stamp)
            .unwrap();
    }

    #[test]
    fn render_row_prints_state_progress_and_optional_parts() {
        let mut model = model(
            "alpha",
            PlanState::Stale {
                since: "09:41".to_string(),
            },
        );
        model.rows[0].done = 3;
        model.rows[0].total = 5;
        model.rows[0].blocked = 2;
        model.rows[0].open_questions = 4;
        model.rows[0].now = Some("waiting on review".to_string());

        let lines: Vec<String> = render(&model).lines().map(str::to_string).collect();
        assert_eq!(
            lines[0],
            "alpha [stale since 09:41] 3/5, 2 blocked | q4 | waiting on review"
        );
    }

    #[test]
    fn render_labels_every_state() {
        assert_eq!(PlanState::Active.label(), "active");
        assert_eq!(PlanState::Blocked.label(), "blocked");
        assert_eq!(PlanState::MergeReady.label(), "merge-ready");
        assert_eq!(PlanState::Waiting.label(), "waiting");
        assert_eq!(PlanState::Finished.label(), "finished");
        assert_eq!(
            PlanState::Stale {
                since: "09:41".to_string()
            }
            .label(),
            "stale since 09:41"
        );
    }

    #[test]
    fn render_omits_empty_optional_parts() {
        let text = render(&model("alpha", PlanState::Active));
        assert!(text.contains("alpha [active] 1/2\n"));
        assert!(!text.contains("blocked"));
        assert!(!text.contains("q0"));
        assert!(!text.contains("blocked tasks:"));
    }

    #[test]
    fn render_sorts_rows_and_blocked_tasks() {
        let model = BlockModel {
            rows: vec![
                row("zulu", PlanState::Finished),
                row("alpha", PlanState::MergeReady),
            ],
            blocked_tasks: vec!["zulu/build".to_string(), "alpha/plan".to_string()],
        };
        let text = render(&model);
        let alpha = text.find("alpha [merge-ready]").unwrap();
        let zulu = text.find("zulu [finished]").unwrap();
        assert!(alpha < zulu);
        assert!(text.contains("blocked tasks: alpha/plan, zulu/build"));
    }

    #[test]
    fn render_includes_lookup_line_last() {
        let text = render(&model("alpha", PlanState::Active));
        assert!(text.ends_with(LOOKUP_LINE));
        assert!(!text.ends_with('\n'));
    }

    #[test]
    fn render_is_stable_on_repeat() {
        let model = model("alpha", PlanState::Waiting);
        assert_eq!(render(&model), render(&model));
    }

    #[test]
    fn render_neutralizes_markers_in_a_now_line() {
        let mut model = model("alpha", PlanState::Active);
        model.rows[0].now = Some(format!("{END_MARKER} oops {BEGIN_MARKER}"));

        let text = render(&model);
        assert_eq!(text.matches(END_MARKER).count(), 0, "{text}");
        assert_eq!(text.matches(BEGIN_MARKER).count(), 0, "{text}");
        assert!(
            text.contains("<!- - varde:plan-status:end --> oops"),
            "{text}"
        );
    }

    #[test]
    fn write_replaces_only_the_marked_region() {
        let root = temp_dir("marked-region");
        let file = root.join(NOTES_FILE);
        fs::write(&file, "# Handwritten\nBefore.\n").unwrap();

        write_block(&file, &model("alpha", PlanState::Active)).unwrap();
        let first = fs::read(&file).unwrap();
        let text = String::from_utf8(first.clone()).unwrap();
        assert!(text.contains("alpha [active] 1/2"));
        assert!(text.contains(BEGIN_MARKER));
        assert!(text.contains(END_MARKER));

        write_block(
            &file,
            &model(
                "alpha",
                PlanState::Stale {
                    since: "10:00".to_string(),
                },
            ),
        )
        .unwrap();
        let second = fs::read(&file).unwrap();
        assert_eq!(outside_markers(&first), outside_markers(&second));
        assert!(
            String::from_utf8(second)
                .unwrap()
                .contains("alpha [stale since 10:00] 1/2")
        );

        fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn write_skips_equal_bytes_and_keeps_mtime() {
        let root = temp_dir("equal-bytes");
        let file = root.join(NOTES_FILE);
        let model = model("alpha", PlanState::Active);
        write_block(&file, &model).unwrap();

        let stamp = SystemTime::UNIX_EPOCH + Duration::from_secs(1_000_000);
        backdate(&file, stamp);
        write_block(&file, &model).unwrap();

        assert_eq!(fs::metadata(&file).unwrap().modified().unwrap(), stamp);
        fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn write_appends_when_no_markers_exist() {
        let root = temp_dir("no-markers");
        let file = root.join(NOTES_FILE);
        let original = b"# Handwritten\nNotes here";
        fs::write(&file, original).unwrap();

        write_block(&file, &model("alpha", PlanState::Active)).unwrap();
        let after = fs::read(&file).unwrap();
        assert!(after.starts_with(original));
        let text = String::from_utf8(after).unwrap();
        assert!(text.contains(BEGIN_MARKER));
        assert!(text.contains("alpha [active] 1/2"));
        assert!(text.ends_with(&format!("{END_MARKER}\n")));

        fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn write_leaves_two_marker_pairs_untouched() {
        let root = temp_dir("two-pairs");
        let file = root.join(NOTES_FILE);
        let original =
            format!("{BEGIN_MARKER}\none\n{END_MARKER}\n{BEGIN_MARKER}\ntwo\n{END_MARKER}\n");
        fs::write(&file, &original).unwrap();

        write_block(&file, &model("alpha", PlanState::Active)).unwrap();
        assert_eq!(fs::read_to_string(&file).unwrap(), original);

        fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn write_leaves_single_unpaired_marker_untouched() {
        let root = temp_dir("one-marker");
        let file = root.join(NOTES_FILE);
        let original = format!("text\n{BEGIN_MARKER}\n");
        fs::write(&file, &original).unwrap();

        write_block(&file, &model("alpha", PlanState::Active)).unwrap();
        assert_eq!(fs::read_to_string(&file).unwrap(), original);

        fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn write_creates_a_draft_stub_when_missing() {
        let root = temp_dir("missing");
        let file = root.join("nested").join(NOTES_FILE);

        write_block(&file, &model("alpha", PlanState::Active)).unwrap();
        let text = fs::read_to_string(&file).unwrap();
        assert!(text.starts_with("---\ntype: session-notes\nstatus: draft\n---\n"));
        assert!(text.contains(BEGIN_MARKER));
        assert!(text.contains("alpha [active] 1/2"));

        fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn write_preserves_a_concurrent_change() {
        let root = temp_dir("concurrent");
        let file = root.join(NOTES_FILE);
        write_block(&file, &model("alpha", PlanState::Active)).unwrap();

        let mut changed = false;
        let mut hook = |target: &Path| {
            if !changed {
                changed = true;
                let mut existing = fs::read(target).unwrap();
                existing.extend_from_slice(b"\nexternal edit\n");
                fs::write(target, existing).unwrap();
            }
        };
        let updated = model(
            "alpha",
            PlanState::Stale {
                since: "10:00".to_string(),
            },
        );
        write_block_inner(&file, &updated, &mut hook).unwrap();

        let text = fs::read_to_string(&file).unwrap();
        assert!(text.contains("external edit"));
        assert!(text.contains("alpha [stale since 10:00] 1/2"));

        fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn write_resolves_a_symlinked_notes_file() {
        let root = temp_dir("symlink");
        let target = root.join("real.md");
        let link = root.join(NOTES_FILE);
        fs::write(&target, "# Real\n").unwrap();
        symlink(&target, &link).unwrap();

        write_block(&link, &model("alpha", PlanState::Active)).unwrap();

        assert!(
            fs::symlink_metadata(&link)
                .unwrap()
                .file_type()
                .is_symlink()
        );
        let text = fs::read_to_string(&target).unwrap();
        assert!(text.contains("alpha [active] 1/2"));

        fs::remove_dir_all(&root).unwrap();
    }
}
