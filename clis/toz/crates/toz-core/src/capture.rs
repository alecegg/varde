//! The capture pipeline: threshold → never-capture → redact → chunk → store → preview.
//!
//! Both `toz run` (owns the child process) and `toz capture` (reads stdin / hook payload) end
//! up here. The preview struct is the output contract described in PLAN.md §2.1.

use crate::chunk::{self, Chunk};
use crate::config::Config;
use crate::profile::{self, PreviewKind, PreviewSpec, Profile};
use crate::redact::{NeverCapture, Redactor};
use crate::script;
use crate::store::{NewCapture, Store};
use anyhow::Result;
use serde::Serialize;
use std::rc::Rc;

/// Bounds for a matched profile's script step: small and fixed, since it runs on every capture
/// that matches, not just an opt-in `toz run`.
const PROFILE_SCRIPT_TIMEOUT_MS: u64 = 1_000;
const PROFILE_SCRIPT_MEMORY_BYTES: usize = 64 * 1024 * 1024;
const PROFILE_SCRIPT_MAX_OUTPUT_BYTES: usize = 4 * 1024;

/// What the caller hands us.
pub struct CaptureInput<'a> {
    pub stdout: &'a [u8],
    pub stderr: &'a [u8],
    pub label: Option<&'a str>,
    /// Human-readable origin: the command, path, or URL.
    pub source: &'a str,
    /// `run` | `capture` | `index` | `fetch` | `hook:<tool>`
    pub kind: &'a str,
    pub exit_code: Option<i32>,
    pub session: Option<&'a str>,
    /// Force capture even under threshold (used by `index` and `fetch`).
    pub force: bool,
    /// Store chunks immediately, but populate search indexes on the first term search.
    pub defer_index: bool,
    pub threshold: Option<usize>,
    /// `index` only: mtime (unix secs) and blake3 hash of the file, for staleness checks.
    pub file_mtime: Option<i64>,
    pub file_hash: Option<Vec<u8>>,
}

impl<'a> CaptureInput<'a> {
    /// Input with no file metadata and no overrides; callers set what they need.
    pub fn new(stdout: &'a [u8], source: &'a str, kind: &'a str) -> Self {
        Self {
            stdout,
            stderr: &[],
            label: None,
            source,
            kind,
            exit_code: None,
            session: None,
            force: false,
            defer_index: false,
            threshold: None,
            file_mtime: None,
            file_hash: None,
        }
    }
}

#[derive(Debug)]
pub enum Outcome {
    /// Under threshold: emit the original bytes untouched.
    PassThrough,
    /// Never-capture rule matched: emit original bytes, store nothing.
    Skipped { rule: &'static str },
    /// Stored; emit the preview instead.
    Captured(Box<Preview>),
}

#[derive(Debug, Clone, Serialize)]
pub struct Preview {
    pub handle: String,
    pub label: String,
    pub bytes: usize,
    pub chunks: usize,
    pub exit_code: Option<i32>,
    pub redactions: usize,
    pub binary: bool,
    pub streamed: bool,
    pub sections: Vec<Section>,
    pub sections_omitted: usize,
    pub head: Vec<String>,
    pub tail: Vec<String>,
    pub stderr_lines: usize,
    pub stderr_head: Vec<String>,
    /// A bounded set of error and warning lines, with stream-local line numbers.
    pub diagnostics: Vec<Diagnostic>,
    /// Total stdout lines (what the section ranges span).
    pub lines: usize,
    /// Distinctive vocabulary worth searching for.
    pub terms: Vec<String>,
    /// A matched profile's `preview = { kind = "toc" }` renders this instead of the fields
    /// above; `None` for the default rendering.
    pub toc: Option<Vec<TocEntry>>,
    /// A matched profile's `script` stdout, when it ran without error, timeout, or a limit hit.
    /// Replaces the whole preview body (below the header line) when present.
    pub script_output: Option<String>,
}

/// One row of a table-of-contents preview (`profile.preview.kind = "toc"`).
#[derive(Debug, Clone, Serialize)]
pub struct TocEntry {
    pub title: String,
    /// Lines in this section matching `preview.item` (or all lines, when `item` is unset).
    pub items: usize,
    pub line_start: usize,
    pub line_end: usize,
    /// The first `preview.items_per_section` of those lines.
    pub lines: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Diagnostic {
    pub stream: String,
    pub line: usize,
    pub level: String,
    pub text: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct Section {
    pub index: usize,
    /// Last chunk index when this row stands for a run of `title (k/m)` parts.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub index_end: Option<usize>,
    pub stream: String,
    pub title: String,
    pub line_start: usize,
    pub line_end: usize,
}

impl Preview {
    /// Text form — what the model reads.
    pub fn render(&self) -> String {
        let mut s = String::new();
        s.push_str(&format!(
            "varde-toz: captured {} → handle {} ({} lines, {} chunk{})  label: {:?}\n",
            fmt_bytes(self.bytes),
            self.handle,
            self.lines,
            self.chunks,
            if self.chunks == 1 { "" } else { "s" },
            self.label
        ));
        if let Some(text) = &self.script_output {
            s.push_str(text);
            if !text.ends_with('\n') {
                s.push('\n');
            }
            self.render_next(&mut s);
            return s;
        }
        if let Some(toc) = &self.toc {
            self.render_toc(&mut s, toc);
            return s;
        }
        self.render_default(&mut s);
        s
    }

    fn render_next(&self, s: &mut String) {
        s.push_str(&format!(
            "next: varde-toz query --handle {h} \"<query>\"   |   varde-toz query --handle {h} --chunk N\n",
            h = self.handle
        ));
    }

    fn render_toc(&self, s: &mut String, toc: &[TocEntry]) {
        for entry in toc {
            s.push_str(&format!(
                "{} ({} items) L{}-L{}\n",
                entry.title, entry.items, entry.line_start, entry.line_end
            ));
            Self::render_lines(s, &entry.lines);
            s.push_str(&format!(
                "read: varde-toz query --handle {} --lines {}:{}\n",
                self.handle, entry.line_start, entry.line_end
            ));
        }
        s.push_str(&format!(
            "search: varde-toz query --handle {} \"<term>\"\n",
            self.handle
        ));
    }

    fn render_default(&self, s: &mut String) {
        if let Some(code) = self.exit_code {
            s.push_str(&format!("varde-toz: exit code {code}\n"));
        }
        if self.redactions > 0 {
            s.push_str(&format!(
                "varde-toz: {} secret-like value(s) redacted\n",
                self.redactions
            ));
        }
        if self.binary {
            s.push_str("varde-toz: legacy binary capture; metadata only, content unavailable\n");
            return;
        }
        if self.streamed {
            s.push_str("varde-toz: streamed text; fixed-size sections, normalized line endings\n");
        }
        self.render_sections(s);
        self.render_samples(s);
        self.render_diagnostics(s);
        if !self.terms.is_empty() {
            s.push_str(&format!("terms: {}\n", self.terms.join(", ")));
        }
        self.render_next(s);
    }

    fn render_sections(&self, s: &mut String) {
        if !self.sections.is_empty() {
            s.push_str("── sections ──────────────────────────────────────────\n");
            for sec in &self.sections {
                let tag = if sec.stream == "stderr" {
                    " [stderr]"
                } else {
                    ""
                };
                let (idx, title) = match sec.index_end {
                    Some(end) => (
                        format!("{}-{}", sec.index, end),
                        format!("{} ({} parts)", sec.title, end - sec.index + 1),
                    ),
                    None => (sec.index.to_string(), sec.title.clone()),
                };
                s.push_str(&format!(
                    "{:>7}  {:<48} L{}-L{}{}\n",
                    idx,
                    chunk::truncate_middle(&title, 48),
                    sec.line_start,
                    sec.line_end,
                    tag
                ));
            }
            if self.sections_omitted > 0 {
                s.push_str(&format!("     … {} more\n", self.sections_omitted));
            }
        }
    }

    fn render_samples(&self, s: &mut String) {
        if !self.head.is_empty() {
            s.push_str(&format!(
                "── head ({} lines) ──────────────────────────────────\n",
                self.head.len()
            ));
            Self::render_lines(s, &self.head);
        }
        if !self.tail.is_empty() {
            s.push_str(&format!(
                "── tail ({} lines) ──────────────────────────────────\n",
                self.tail.len()
            ));
            Self::render_lines(s, &self.tail);
        }
        if self.stderr_lines > 0 && !self.stderr_head.is_empty() {
            s.push_str(&format!(
                "── stderr ({} lines) ────────────────────────────────\n",
                self.stderr_lines
            ));
            Self::render_lines(s, &self.stderr_head);
        }
    }

    fn render_lines(s: &mut String, lines: &[String]) {
        for line in lines {
            s.push_str(line);
            s.push('\n');
        }
    }

    fn render_diagnostics(&self, s: &mut String) {
        if !self.diagnostics.is_empty() {
            s.push_str("── diagnostics ───────────────────────────────────────\n");
            for diagnostic in &self.diagnostics {
                s.push_str(&format!(
                    "{} L{} [{}] {}\n",
                    diagnostic.stream, diagnostic.line, diagnostic.level, diagnostic.text
                ));
            }
        }
    }
}

pub fn fmt_bytes(n: usize) -> String {
    let s = n.to_string();
    let mut out = String::new();
    for (i, c) in s.chars().enumerate() {
        if i > 0 && (s.len() - i).is_multiple_of(3) {
            out.push(',');
        }
        out.push(c);
    }
    format!("{out} bytes")
}

/// A single-line JSON body (minified API responses, `cargo metadata`, …) can't be chunked or
/// line-addressed, so it is stored pretty-printed instead. Multi-line bodies are kept verbatim.
pub fn expand_minified_json(text: String) -> String {
    let trimmed = text.trim();
    if trimmed.lines().count() > 2 || !(trimmed.starts_with('{') || trimmed.starts_with('[')) {
        return text;
    }
    match serde_json::from_str::<serde_json::Value>(trimmed) {
        Ok(v) => serde_json::to_string_pretty(&v).unwrap_or(text),
        Err(_) => text,
    }
}

/// Normalise a source string into a supersession key.
pub fn source_key(source: &str) -> String {
    let mut s = source.trim().to_string();
    for suffix in [" 2>&1", " 2>/dev/null", " 2> /dev/null"] {
        if let Some(stripped) = s.strip_suffix(suffix) {
            s = stripped.to_string();
        }
    }
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

pub fn run(
    cfg: &Config,
    store: &mut Store,
    input: CaptureInput,
    profiles: &[Profile],
) -> Result<Outcome> {
    let total = input.stdout.len() + input.stderr.len();
    if !input.force && total <= input.threshold.unwrap_or(cfg.threshold) {
        return Ok(Outcome::PassThrough);
    }

    let (label, sk) = capture_names(&input);
    let never = NeverCapture::from_config(&cfg.capture)?;
    if never.matches(&sk) || never.matches(input.source) {
        return Ok(Outcome::Skipped {
            rule: "never-capture",
        });
    }

    let binary = chunk::looks_binary(input.stdout) || chunk::looks_binary(input.stderr);
    if binary {
        return Ok(Outcome::Skipped { rule: "binary" });
    }
    capture_accepted(cfg, store, input, profiles, total, label, sk)
}

fn capture_names(input: &CaptureInput<'_>) -> (String, String) {
    let key = source_key(input.source);
    let label = input
        .label
        .map(str::to_string)
        .unwrap_or_else(|| chunk::truncate(&key, 120));
    // An explicit label is the supersession key when given; otherwise the normalised source.
    let source_key = input.label.map(|l| l.trim().to_string()).unwrap_or(key);
    (label, source_key)
}

#[allow(clippy::too_many_arguments)]
fn capture_accepted(
    cfg: &Config,
    store: &mut Store,
    input: CaptureInput<'_>,
    profiles: &[Profile],
    total: usize,
    label: String,
    sk: String,
) -> Result<Outcome> {
    // A hook or wrapped-command origin is a literal command line; index/fetch/script origins
    // are paths or URLs, so only `match.source` (never `match.command`) applies to them.
    let is_command = input.kind == "run" || input.kind.starts_with("hook:");
    let matched = profile::find_match(profiles, input.source, is_command);
    let redactor = Redactor::from_config(&cfg.redact)?;
    let (all_chunks, redactions, stdout_text, stderr_text) =
        prepare_text(&input, &redactor, matched);

    let new = NewCapture {
        label: &label,
        kind: input.kind,
        source: input.source,
        source_key: &sk,
        bytes: total,
        exit_code: input.exit_code,
        session: input.session,
        redactions,
        binary: false,
        file_mtime: input.file_mtime,
        file_hash: input.file_hash.as_deref(),
    };
    let handle = store.insert_capture_indexed(&new, &all_chunks, !input.defer_index)?;

    let script_output = capture_script_output(
        store,
        matched,
        &handle,
        &label,
        total,
        input.exit_code,
        &stdout_text,
        &stderr_text,
    );
    let preview = build_preview(
        cfg,
        handle,
        label,
        total,
        input.exit_code,
        redactions,
        false,
        &all_chunks,
        &stdout_text,
        &stderr_text,
        matched,
        script_output,
    );
    let out_len = preview.render().len();
    store.log_stats(input.kind, total, out_len, input.session)?;
    Ok(Outcome::Captured(Box::new(preview)))
}

#[allow(clippy::too_many_arguments)]
fn capture_script_output(
    store: &mut Store,
    matched: Option<&Profile>,
    handle: &str,
    label: &str,
    total: usize,
    exit_code: Option<i32>,
    stdout_text: &str,
    stderr_text: &str,
) -> Option<String> {
    let profile = matched.filter(|p| p.has_script())?;
    let meta = script::Meta {
        handle: handle.to_string(),
        label: label.to_string(),
        bytes: total as i64,
        lines: stdout_text.lines().count() as i64,
        exit_code,
        stream: "stdout".into(),
    };
    run_profile_script(store, profile, meta, stdout_text, stderr_text)
}

fn prepare_text(
    input: &CaptureInput<'_>,
    redactor: &Redactor,
    matched: Option<&Profile>,
) -> (Vec<(String, Chunk)>, usize, String, String) {
    let (stdout, r1) = redactor.apply(&chunk::strip_ansi(&String::from_utf8_lossy(input.stdout)));
    let (stderr, r2) = redactor.apply(&chunk::strip_ansi(&String::from_utf8_lossy(input.stderr)));
    let stdout = expand_minified_json(stdout);
    let chunks = chunk::chunk_for(&stdout, matched)
        .into_iter()
        .map(|c| ("stdout".into(), c))
        .chain(
            chunk::chunk_for(&stderr, matched)
                .into_iter()
                .map(|c| ("stderr".into(), c)),
        )
        .collect();
    (chunks, r1 + r2, stdout, stderr)
}

/// Run a matched profile's script against a fresh capture and persist the outcome: its
/// `toz.record()` calls on success, or a diagnostic on error, timeout, or a limit hit (including
/// a call to `toz.exec`, which is not installed for a profile script and so throws). Either way
/// the capture itself has already succeeded; a script problem only loses the script's preview.
fn run_profile_script(
    store: &mut Store,
    profile: &Profile,
    meta: script::Meta,
    stdout_text: &str,
    stderr_text: &str,
) -> Option<String> {
    let script_src = profile.script.as_deref()?;
    let capture_id = store
        .get_by_handle(&meta.handle)
        .ok()
        .flatten()
        .map(|r| r.id);

    let limits = script::Limits {
        timeout_ms: PROFILE_SCRIPT_TIMEOUT_MS,
        memory_bytes: PROFILE_SCRIPT_MEMORY_BYTES,
        max_output_bytes: PROFILE_SCRIPT_MAX_OUTPUT_BYTES,
        ..script::Limits::default()
    };
    let src: Rc<dyn script::LineSource> = Rc::new(script::TextLines::new(stdout_text, stderr_text));

    let diagnose = |store: &mut Store, reason: String| {
        if let Some(id) = capture_id {
            let _ = store.insert_profile_diagnostic(id, &profile.id, &reason);
        }
    };

    match script::run(script_src, &meta, src, &limits) {
        Ok((script::Outcome::Ok(text), records)) => {
            if let Some(id) = capture_id {
                if !records.is_empty() {
                    let rows: Vec<(String, String)> =
                        records.into_iter().map(|r| (r.kind, r.json)).collect();
                    if let Err(e) = store.insert_records(id, &rows) {
                        diagnose(store, format!("record persistence failed: {e:#}"));
                    }
                }
            }
            Some(text)
        }
        Ok((other, _)) => {
            diagnose(store, script_outcome_reason(&other));
            None
        }
        Err(e) => {
            diagnose(store, format!("script error: {e:#}"));
            None
        }
    }
}

fn script_outcome_reason(outcome: &script::Outcome) -> String {
    match outcome {
        script::Outcome::Exception(msg) => format!("script exception: {msg}"),
        script::Outcome::Timeout => "script timed out".to_string(),
        script::Outcome::MemoryLimit => "script exceeded memory limit".to_string(),
        script::Outcome::OutputLimit => "script exceeded output limit".to_string(),
        script::Outcome::Ok(_) => unreachable!("Ok is handled by the caller"),
    }
}

/// How many distinctive terms a preview lists.
const PREVIEW_TERMS: usize = 12;

/// Longest line the preview will echo; a minified 100 KB line must not defeat the point.
const PREVIEW_LINE_MAX: usize = 240;
const PREVIEW_DIAGNOSTICS: usize = 6;

fn preview_line(s: &str) -> String {
    chunk::truncate(s, PREVIEW_LINE_MAX)
}

fn diagnostic_level(line: &str) -> Option<&'static str> {
    let trimmed = line.trim_start();
    let lower = trimmed
        .chars()
        .take(512)
        .collect::<String>()
        .to_ascii_lowercase();
    if lower.starts_with("error:")
        || lower.starts_with("error[")
        || lower.starts_with("fatal:")
        || lower.contains(": error:")
        || lower.contains("panicked at ")
        || lower.ends_with(" ... failed")
        || lower.starts_with("test result: failed")
    {
        Some("error")
    } else if lower.starts_with("warning:")
        || lower.starts_with("warning[")
        || lower.contains(": warning:")
    {
        Some("warning")
    } else {
        None
    }
}

pub(crate) fn push_diagnostic(
    diagnostics: &mut Vec<Diagnostic>,
    stream: &str,
    line: usize,
    text: &str,
) {
    let Some(level) = diagnostic_level(text) else {
        return;
    };
    let diagnostic = Diagnostic {
        stream: stream.to_string(),
        line,
        level: level.to_string(),
        text: preview_line(text),
    };
    if diagnostics.len() < PREVIEW_DIAGNOSTICS {
        diagnostics.push(diagnostic);
    } else if level == "error" {
        if let Some(index) = diagnostics.iter().position(|item| item.level == "warning") {
            diagnostics.remove(index);
            diagnostics.push(diagnostic);
        }
    }
}

pub(crate) fn stderr_signature(line: &str, count: usize) -> String {
    if count == 1 {
        return preview_line(line);
    }
    let suffix = format!(" ×{count}");
    let content_limit = PREVIEW_LINE_MAX.saturating_sub(suffix.chars().count());
    format!("{}{suffix}", chunk::truncate(line, content_limit))
}

/// Collects adjacent stderr lines and blank-separated blocks.
pub(crate) struct StderrSignatures {
    limit: usize,
    entries: Vec<String>,
    current_block: Vec<String>,
    previous_block: Option<(Vec<String>, usize)>,
}

impl StderrSignatures {
    pub(crate) fn new(limit: usize) -> Self {
        Self {
            limit,
            entries: Vec::with_capacity(limit),
            current_block: Vec::new(),
            previous_block: None,
        }
    }

    pub(crate) fn push(&mut self, line: &str) {
        if line.trim().is_empty() {
            self.finish_block();
        } else {
            self.current_block.push(line.to_string());
        }
    }

    fn finish_block(&mut self) {
        if self.current_block.is_empty() {
            return;
        }
        let block = std::mem::take(&mut self.current_block);
        match self.previous_block.take() {
            Some((previous, count)) if previous == block => {
                self.previous_block = Some((previous, count + 1));
            }
            Some((previous, count)) => {
                self.emit_block(&previous, count);
                self.previous_block = Some((block, 1));
            }
            None => self.previous_block = Some((block, 1)),
        }
    }

    fn emit_block(&mut self, block: &[String], count: usize) {
        if self.entries.len() >= self.limit {
            return;
        }
        let lines: Vec<&str> = block.iter().map(String::as_str).collect();
        let compressed = collapse_line_group(&lines);
        let visible = compressed.len().min(self.limit - self.entries.len());
        for (index, line) in compressed.into_iter().take(visible).enumerate() {
            let is_last = index + 1 == visible;
            if is_last && count > 1 {
                self.entries.push(stderr_signature(&line, count));
            } else {
                self.entries.push(line);
            }
        }
    }

    pub(crate) fn finish(mut self) -> Vec<String> {
        self.finish_block();
        if let Some((block, count)) = self.previous_block.take() {
            self.emit_block(&block, count);
        }
        self.entries
    }
}

fn collapse_line_group(lines: &[&str]) -> Vec<String> {
    let mut out = Vec::new();
    let mut current: Option<(&str, usize)> = None;
    for &line in lines {
        match current {
            Some((previous, count)) if previous == line => {
                current = Some((previous, count + 1));
            }
            Some((previous, count)) => {
                out.push(stderr_signature(previous, count));
                current = Some((line, 1));
            }
            None => current = Some((line, 1)),
        }
    }
    if let Some((line, count)) = current {
        out.push(stderr_signature(line, count));
    }
    out
}

fn collapse_stderr_lines(lines: &[&str], limit: usize) -> Vec<String> {
    let mut signatures = StderrSignatures::new(limit);
    for line in lines {
        signatures.push(line);
    }
    signatures.finish()
}

/// `"Cargo.lock (3/26)"` → `Some("Cargo.lock")`.
fn part_base(title: &str) -> Option<&str> {
    let t = title.strip_suffix(')')?;
    let open = t.rfind(" (")?;
    let inner = &t[open + 2..];
    let (a, b) = inner.split_once('/')?;
    if a.chars().all(|c| c.is_ascii_digit())
        && b.chars().all(|c| c.is_ascii_digit())
        && !a.is_empty()
        && !b.is_empty()
    {
        Some(&t[..open])
    } else {
        None
    }
}

#[allow(clippy::too_many_arguments)]
fn build_preview(
    cfg: &Config,
    handle: String,
    label: String,
    bytes: usize,
    exit_code: Option<i32>,
    redactions: usize,
    binary: bool,
    chunks: &[(String, Chunk)],
    stdout_text: &str,
    stderr_text: &str,
    profile: Option<&Profile>,
    script_output: Option<String>,
) -> Preview {
    let sections = preview_sections(chunks);
    let out_lines: Vec<&str> = stdout_text.lines().collect();
    let err_lines: Vec<&str> = stderr_text.lines().collect();
    let (head, tail) = preview_head_tail(cfg, &out_lines);
    let stderr_head = collapse_stderr_lines(&err_lines, cfg.preview_tail);
    let diagnostics = preview_diagnostics(&out_lines, &err_lines);
    let toc = profile
        .and_then(|p| p.preview.as_ref())
        .filter(|spec| matches!(spec.kind, PreviewKind::Toc))
        .map(|spec| build_toc(&sections, &out_lines, &err_lines, spec));
    let shown = sections.len().min(cfg.preview_sections);
    let omitted = sections.len() - shown;

    Preview {
        handle,
        label,
        bytes,
        chunks: chunks.len(),
        exit_code,
        redactions,
        binary,
        sections: sections.into_iter().take(shown).collect(),
        streamed: false,
        sections_omitted: omitted,
        head,
        tail,
        stderr_lines: err_lines.len(),
        stderr_head,
        diagnostics,
        lines: out_lines.len(),
        terms: crate::terms::distinctive(
            &chunks
                .iter()
                .filter(|(stream, _)| stream == "stdout")
                .map(|(_, c)| c.body.as_str())
                .collect::<Vec<_>>(),
            PREVIEW_TERMS,
        ),
        toc,
        script_output,
    }
}

fn preview_sections(chunks: &[(String, Chunk)]) -> Vec<Section> {
    // One row per chunk, except that consecutive `title (k/m)` parts collapse into one row
    // so a big file in a diff doesn't crowd out the rest of the list.
    let mut sections: Vec<Section> = Vec::with_capacity(chunks.len());
    for (i, (stream, c)) in chunks.iter().enumerate() {
        let base = part_base(&c.title);
        if let (Some(b), Some(last)) = (base, sections.last_mut()) {
            if last.stream == *stream
                && last.title == b
                && last.index_end.map_or(last.index + 1 == i, |e| e + 1 == i)
            {
                last.index_end = Some(i);
                last.line_end = c.line_end;
                continue;
            }
        }
        sections.push(Section {
            index: i,
            index_end: None,
            stream: stream.clone(),
            title: base.map(str::to_string).unwrap_or_else(|| c.title.clone()),
            line_start: c.line_start,
            line_end: c.line_end,
        });
    }
    // A lone part keeps its full title.
    for sec in sections.iter_mut() {
        if sec.index_end.is_none() {
            if let Some((_, c)) = chunks.get(sec.index) {
                sec.title = c.title.clone();
            }
        }
    }
    sections
}

fn preview_head_tail(cfg: &Config, out_lines: &[&str]) -> (Vec<String>, Vec<String>) {
    let head: Vec<String> = out_lines
        .iter()
        .take(cfg.preview_head)
        .map(|s| preview_line(s))
        .collect();
    let tail: Vec<String> = if out_lines.len() > cfg.preview_head {
        let start = out_lines
            .len()
            .saturating_sub(cfg.preview_tail)
            .max(cfg.preview_head);
        out_lines[start..].iter().map(|s| preview_line(s)).collect()
    } else {
        Vec::new()
    };
    (head, tail)
}

fn preview_diagnostics(out_lines: &[&str], err_lines: &[&str]) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    for (index, line) in out_lines.iter().enumerate() {
        push_diagnostic(&mut diagnostics, "stdout", index + 1, line);
    }
    for (index, line) in err_lines.iter().enumerate() {
        push_diagnostic(&mut diagnostics, "stderr", index + 1, line);
    }
    diagnostics
}

/// One `TocEntry` per section, per `profile.preview = { kind = "toc", ... }`.
fn build_toc(
    sections: &[Section],
    out_lines: &[&str],
    err_lines: &[&str],
    spec: &PreviewSpec,
) -> Vec<TocEntry> {
    sections
        .iter()
        .map(|sec| {
            let source = if sec.stream == "stderr" {
                err_lines
            } else {
                out_lines
            };
            let start = sec.line_start.saturating_sub(1).min(source.len());
            let end = sec.line_end.min(source.len());
            let slice = &source[start..end];
            let matching: Vec<&str> = match &spec.item {
                Some(re) => slice.iter().copied().filter(|l| re.is_match(l)).collect(),
                None => slice.to_vec(),
            };
            let items = matching.len();
            let take = spec.items_per_section.unwrap_or(items);
            let title = match sec.index_end {
                Some(end) => format!("{} ({} parts)", sec.title, end - sec.index + 1),
                None => sec.title.clone(),
            };
            TocEntry {
                title,
                items,
                line_start: sec.line_start,
                line_end: sec.line_end,
                lines: matching.into_iter().take(take).map(preview_line).collect(),
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_key_normalises() {
        assert_eq!(source_key("  cargo   test  2>&1"), "cargo test");
        assert_eq!(source_key("git diff"), "git diff");
    }

    #[test]
    fn fmt_bytes_groups() {
        assert_eq!(fmt_bytes(184203), "184,203 bytes");
        assert_eq!(fmt_bytes(12), "12 bytes");
    }

    #[test]
    fn repeated_stderr_lines_render_as_counted_signatures() {
        let cfg = Config::default();
        let stderr = "warning\nwarning\nwarning\nnext\nnext\n";
        let chunks = chunk::chunk_default(stderr)
            .into_iter()
            .map(|chunk| ("stderr".to_string(), chunk))
            .collect::<Vec<_>>();

        let preview = build_preview(
            &cfg,
            "h".to_string(),
            "test".to_string(),
            stderr.len(),
            Some(1),
            0,
            false,
            &chunks,
            "",
            stderr,
            None,
            None,
        );

        assert_eq!(preview.stderr_lines, 5);
        assert_eq!(
            preview.stderr_head,
            vec!["warning ×3".to_string(), "next ×2".to_string()]
        );
    }

    #[test]
    fn repeated_stderr_blocks_render_once_with_count() {
        let cfg = Config::default();
        let stderr = "error: boom\n  at main\n\nerror: boom\n  at main\n\nerror: boom\n  at main\n";
        let chunks = chunk::chunk_default(stderr)
            .into_iter()
            .map(|chunk| ("stderr".to_string(), chunk))
            .collect::<Vec<_>>();

        let preview = build_preview(
            &cfg,
            "h".to_string(),
            "test".to_string(),
            stderr.len(),
            Some(1),
            0,
            false,
            &chunks,
            "",
            stderr,
            None,
            None,
        );

        assert_eq!(preview.stderr_lines, 8);
        assert_eq!(
            preview.stderr_head,
            vec!["error: boom".to_string(), "  at main ×3".to_string(),]
        );
    }

    #[test]
    fn diagnostics_surface_middle_errors_with_stream_local_lines() {
        let cfg = Config {
            preview_head: 1,
            preview_tail: 1,
            ..Default::default()
        };
        let stdout = "start\nworking\nerror: build failed\nend\n";
        let stderr = "notice\nwarning: retrying\n";
        let preview = build_preview(
            &cfg,
            "h".into(),
            "test".into(),
            stdout.len() + stderr.len(),
            Some(1),
            0,
            false,
            &[],
            stdout,
            stderr,
            None,
            None,
        );
        let rendered = preview.render();
        assert!(rendered.contains("stdout L3 [error] error: build failed"));
        assert!(rendered.contains("stderr L2 [warning] warning: retrying"));
        assert_eq!(preview.head, vec!["start"]);
        assert_eq!(preview.tail, vec!["end"]);
    }

    #[test]
    fn diagnostic_count_is_bounded_and_errors_replace_warnings() {
        let mut diagnostics = Vec::new();
        for index in 0..10 {
            push_diagnostic(&mut diagnostics, "stdout", index + 1, "warning: noisy");
        }
        push_diagnostic(&mut diagnostics, "stdout", 11, "error: important");
        assert_eq!(diagnostics.len(), PREVIEW_DIAGNOSTICS);
        assert!(diagnostics
            .iter()
            .any(|item| item.line == 11 && item.level == "error"));
        assert!(diagnostics
            .iter()
            .all(|item| item.text.len() <= PREVIEW_LINE_MAX));
    }

    #[test]
    fn render_leads_sections_with_known_exit_code() {
        let preview = Preview {
            handle: "h".into(),
            label: "test".into(),
            bytes: 1,
            chunks: 1,
            exit_code: Some(0),
            redactions: 0,
            binary: false,
            streamed: false,
            sections: vec![Section {
                index: 0,
                index_end: None,
                stream: "stdout".into(),
                title: "output".into(),
                line_start: 1,
                line_end: 1,
            }],
            sections_omitted: 0,
            head: vec!["output".into()],
            tail: Vec::new(),
            stderr_lines: 0,
            stderr_head: Vec::new(),
            diagnostics: Vec::new(),
            lines: 1,
            terms: Vec::new(),
            toc: None,
            script_output: None,
        };
        let rendered = preview.render();
        assert!(rendered.contains("varde-toz: exit code 0"));
        assert!(
            rendered.find("varde-toz: exit code 0").unwrap()
                < rendered.find("── sections").unwrap()
        );
    }

    fn open_test_store() -> Store {
        let dir = tempfile::tempdir().unwrap();
        Store::open(&dir.path().join("toz.db")).unwrap()
    }

    #[test]
    fn matched_heading_profile_renders_a_toc_preview() {
        use crate::profile::{
            GlobPattern, MatchSpec, PreviewKind, PreviewSpec, Profile, Scope, SectionsSpec,
        };
        let text = "## Section One\nline1\nline2\nline3\n## Section Two\nlineA\nlineB\nlineC\n";
        let profile = Profile {
            id: "headings".into(),
            scope: Scope::Project,
            file: "<test>".into(),
            match_spec: Some(MatchSpec::Source(GlobPattern::compile("test").unwrap())),
            sections: Some(SectionsSpec::Heading(
                regex::Regex::new(r"^## (.+)$").unwrap(),
            )),
            merge_small: false,
            preview: Some(PreviewSpec {
                kind: PreviewKind::Toc,
                items_per_section: None,
                item: None,
            }),
            script: None,
            tests: Vec::new(),
        };
        let mut store = open_test_store();
        let mut input = CaptureInput::new(text.as_bytes(), "test", "capture");
        input.force = true;
        let Outcome::Captured(preview) = run(
            &Config::default(),
            &mut store,
            input,
            std::slice::from_ref(&profile),
        )
        .unwrap() else {
            panic!("expected captured output");
        };
        let rendered = preview.render();
        assert!(rendered.contains("Section One (4 items) L1-L4"));
        assert!(rendered.contains("Section Two (4 items) L5-L8"));
        assert!(rendered.contains(&format!(
            "read: varde-toz query --handle {} --lines 1:4",
            preview.handle
        )));
        assert!(rendered.contains(&format!(
            "search: varde-toz query --handle {} \"<term>\"",
            preview.handle
        )));
    }

    #[test]
    fn jsonl_key_profile_groups_toc_sections_by_field_value() {
        use crate::profile::{
            GlobPattern, MatchSpec, PreviewKind, PreviewSpec, Profile, Scope, SectionsSpec,
        };
        let text = concat!(
            "{\"file\":\"a.rs\",\"msg\":\"one\"}\n",
            "{\"file\":\"a.rs\",\"msg\":\"two\"}\n",
            "{\"file\":\"b.rs\",\"msg\":\"three\"}\n",
        );
        let profile = Profile {
            id: "jsonl".into(),
            scope: Scope::Project,
            file: "<test>".into(),
            match_spec: Some(MatchSpec::Source(GlobPattern::compile("test").unwrap())),
            sections: Some(SectionsSpec::JsonlKey("file".into())),
            merge_small: false,
            preview: Some(PreviewSpec {
                kind: PreviewKind::Toc,
                items_per_section: None,
                item: None,
            }),
            script: None,
            tests: Vec::new(),
        };
        let mut store = open_test_store();
        let mut input = CaptureInput::new(text.as_bytes(), "test", "capture");
        input.force = true;
        let Outcome::Captured(preview) = run(
            &Config::default(),
            &mut store,
            input,
            std::slice::from_ref(&profile),
        )
        .unwrap() else {
            panic!("expected captured output");
        };
        let rendered = preview.render();
        assert!(rendered.contains("a.rs (2 items) L1-L2"));
        assert!(rendered.contains("b.rs (1 items) L3-L3"));
    }

    fn script_profile(id: &str, source_pattern: &str, script: &str) -> Profile {
        use crate::profile::{GlobPattern, MatchSpec, Scope};
        Profile {
            id: id.into(),
            scope: Scope::Project,
            file: "<test>".into(),
            match_spec: Some(MatchSpec::Source(
                GlobPattern::compile(source_pattern).unwrap(),
            )),
            sections: None,
            merge_small: true,
            preview: None,
            script: Some(script.into()),
            tests: Vec::new(),
        }
    }

    #[test]
    fn script_preview_replaces_body_and_persists_records() {
        let text = "a\nb\nc\n";
        let profile = script_profile(
            "counter",
            "script-ok",
            "let n = 0; toz.eachLine(l => { n++; toz.record('line', {l}); }); print('lines: ' + n);",
        );
        let mut store = open_test_store();
        let mut input = CaptureInput::new(text.as_bytes(), "script-ok", "capture");
        input.force = true;
        let Outcome::Captured(preview) = run(
            &Config::default(),
            &mut store,
            input,
            std::slice::from_ref(&profile),
        )
        .unwrap() else {
            panic!("expected captured output");
        };
        assert_eq!(preview.script_output.as_deref(), Some("lines: 3\n"));
        let rendered = preview.render();
        assert!(rendered.starts_with("varde-toz: captured"));
        assert!(rendered.contains("lines: 3"));
        assert!(!rendered.contains("── sections"));

        let row = store.get_by_handle(&preview.handle).unwrap().unwrap();
        let records = store.records_for(row.id, "line").unwrap();
        assert_eq!(
            records,
            vec![
                "{\"l\":\"a\"}".to_string(),
                "{\"l\":\"b\"}".to_string(),
                "{\"l\":\"c\"}".to_string(),
            ]
        );
        assert!(store.recent_profile_diagnostics(10).unwrap().is_empty());
    }

    #[test]
    fn script_throw_and_exec_call_fall_back_to_default_preview_and_record_a_diagnostic() {
        let text = "a\nb\n";
        for (id, source, script) in [
            (
                "script-throw",
                "script-throw-src",
                "throw new Error('boom')",
            ),
            // `toz.exec` is never installed for a profile script (no `CommandCaller` is
            // passed), so calling it throws like any other undefined function.
            ("script-exec", "script-exec-src", "toz.exec({shell:'true'})"),
        ] {
            let profile = script_profile(id, source, script);
            let mut store = open_test_store();
            let mut input = CaptureInput::new(text.as_bytes(), source, "capture");
            input.force = true;
            let Outcome::Captured(preview) = run(
                &Config::default(),
                &mut store,
                input,
                std::slice::from_ref(&profile),
            )
            .unwrap() else {
                panic!("expected captured output, case {id}");
            };
            assert!(preview.script_output.is_none(), "case {id}");
            assert!(preview.render().contains("── sections"), "case {id}");
            let diags = store.recent_profile_diagnostics(10).unwrap();
            assert_eq!(diags.len(), 1, "case {id}");
            assert_eq!(diags[0].profile_id, id);
        }
    }

    #[test]
    fn script_timeout_falls_back_to_default_preview_and_records_a_diagnostic() {
        let text = "a\n";
        let profile = script_profile("script-loop", "script-loop-src", "while (true) {}");
        let mut store = open_test_store();
        let mut input = CaptureInput::new(text.as_bytes(), "script-loop-src", "capture");
        input.force = true;
        let Outcome::Captured(preview) = run(
            &Config::default(),
            &mut store,
            input,
            std::slice::from_ref(&profile),
        )
        .unwrap() else {
            panic!("expected captured output");
        };
        assert!(preview.script_output.is_none());
        assert!(preview.render().contains("── sections"));
        let diags = store.recent_profile_diagnostics(10).unwrap();
        assert_eq!(diags.len(), 1);
        assert!(diags[0].reason.contains("timed out"), "{}", diags[0].reason);
    }
}
