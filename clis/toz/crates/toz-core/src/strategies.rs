//! Content-aware chunkers (PLAN.md §4). Each strategy turns a body into a list of *segments*
//! (line ranges with a title); the shared post-pass then splits oversized segments and merges
//! tiny neighbours so chunk sizes stay search-friendly. Chunks are always contiguous and
//! cover the whole body, which `Store::full_text` relies on.
//!
//! Strategies are picked by sniffing, in this order: diff, JSON, source code, markdown, test
//! output, log, then the fixed-window fallback in `chunk.rs`.

use crate::chunk::{classify, title_for, truncate_middle, Chunk, Chunker, FixedWindow};
use crate::profile::{Profile, SectionsSpec};
use regex::Regex;
use std::sync::LazyLock;

/// Segments above this many bytes get sub-split (at blank lines when possible).
const MAX_BYTES: usize = 3 * 1024;
/// …and above this many lines regardless of bytes.
const MAX_LINES: usize = 120;
/// Segments below this get merged into the next one.
const MIN_BYTES: usize = 300;

#[derive(Debug, Clone)]
struct Segment {
    /// 0-based, inclusive start line.
    start: usize,
    /// 0-based, exclusive end line.
    end: usize,
    title: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Strategy {
    Diff,
    Json,
    Markdown,
    Test,
    Log,
    Code,
    Fixed,
}

/// Sniff the body and pick a strategy.
pub fn detect(text: &str) -> Strategy {
    let lines: Vec<&str> = text.lines().collect();
    if lines.len() < 4 {
        return Strategy::Fixed;
    }
    // Code goes before markdown/test/log: source files contain "error"/"warn" (log-like) and
    // `# comment` lines (heading-like), but nothing else classifies as code *and* has
    // definition lines.
    if looks_like_diff(&lines) {
        return Strategy::Diff;
    }
    if looks_like_json(text, &lines) {
        return Strategy::Json;
    }
    let classifiers: [(fn(&[&str]) -> bool, Strategy); 4] = [
        (looks_like_code, Strategy::Code),
        (looks_like_markdown, Strategy::Markdown),
        (looks_like_test_output, Strategy::Test),
        (looks_like_log, Strategy::Log),
    ];
    for (matches, strategy) in classifiers {
        if matches(&lines) {
            return strategy;
        }
    }
    Strategy::Fixed
}

/// The sniffed strategy's segments (empty for `Fixed`, which callers handle separately since it
/// bypasses segmenting entirely).
fn strategy_segments(strategy: Strategy, lines: &[&str]) -> Vec<Segment> {
    match strategy {
        Strategy::Diff => diff_segments(lines),
        Strategy::Json => json_segments(lines),
        Strategy::Markdown => markdown_segments(lines),
        Strategy::Test => test_segments(lines),
        Strategy::Log => log_segments(lines),
        Strategy::Code => code_segments(lines),
        Strategy::Fixed => Vec::new(),
    }
}

pub fn chunk_with(strategy: Strategy, text: &str) -> Vec<Chunk> {
    let lines: Vec<&str> = text.lines().collect();
    if lines.is_empty() {
        return Vec::new();
    }
    if strategy == Strategy::Fixed {
        return FixedWindow::default().chunk(text);
    }
    finish_segments(strategy_segments(strategy, &lines), &lines, text, true)
}

/// Section a body per a matched profile: `profile.sections` replaces the sniffed strategy when
/// set, and `profile.merge_small` controls whether the shared post-pass folds tiny neighbours.
pub fn chunk_with_profile(text: &str, profile: &Profile) -> Vec<Chunk> {
    let lines: Vec<&str> = text.lines().collect();
    if lines.is_empty() {
        return Vec::new();
    }
    let segments = match &profile.sections {
        Some(SectionsSpec::Heading(re)) => heading_segments(re, &lines),
        Some(SectionsSpec::Start(re)) => start_segments(re, &lines),
        Some(SectionsSpec::JsonlKey(key)) => jsonl_key_segments(key, &lines),
        None => {
            let strategy = detect(text);
            if strategy == Strategy::Fixed {
                return FixedWindow::default().chunk(text);
            }
            strategy_segments(strategy, &lines)
        }
    };
    finish_segments(segments, &lines, text, profile.merge_small)
}

/// Each line matching `re` starts a new section; capture group 1 (or the whole match, if the
/// pattern has no group) titles it.
fn heading_segments(re: &Regex, lines: &[&str]) -> Vec<Segment> {
    let mut segs = Vec::new();
    for (i, line) in lines.iter().enumerate() {
        if let Some(caps) = re.captures(line) {
            let title = caps
                .get(1)
                .or_else(|| caps.get(0))
                .map(|m| m.as_str().to_string())
                .unwrap_or_default();
            segs.push(Segment {
                start: i,
                end: lines.len(),
                title,
            });
        }
    }
    segs
}

/// Each line matching `re` starts a new section; the matched text titles it.
fn start_segments(re: &Regex, lines: &[&str]) -> Vec<Segment> {
    let mut segs = Vec::new();
    for (i, line) in lines.iter().enumerate() {
        if let Some(m) = re.find(line) {
            segs.push(Segment {
                start: i,
                end: lines.len(),
                title: m.as_str().to_string(),
            });
        }
    }
    segs
}

/// Consecutive JSON-Lines with the same value at `key` form one section, titled by that value.
/// Dots traverse nested object keys, e.g. `location.file`.
fn jsonl_key_segments(key: &str, lines: &[&str]) -> Vec<Segment> {
    let mut segs: Vec<Segment> = Vec::new();
    let mut current: Option<String> = None;
    for (i, line) in lines.iter().enumerate() {
        let value = serde_json::from_str::<serde_json::Value>(line.trim())
            .ok()
            .and_then(|v| {
                key.split('.')
                    .try_fold(&v, |node, part| node.get(part))
                    .cloned()
            })
            .map(|v| {
                v.as_str()
                    .map(str::to_string)
                    .unwrap_or_else(|| v.to_string())
            });
        if value != current {
            segs.push(Segment {
                start: i,
                end: lines.len(),
                title: value.clone().unwrap_or_default(),
            });
            current = value;
        }
    }
    segs
}

/// Shared tail of `chunk_with`/`chunk_with_profile`: normalise segments, then turn them into
/// `Chunk`s. `text` is the fallback-to-fixed-window source when segmenting yields nothing.
fn finish_segments(
    segments: Vec<Segment>,
    lines: &[&str],
    text: &str,
    merge_small: bool,
) -> Vec<Chunk> {
    let segments = normalise(segments, lines, merge_small);
    if segments.is_empty() {
        return FixedWindow::default().chunk(text);
    }
    segments
        .into_iter()
        .enumerate()
        .map(|(ordinal, s)| {
            let slice = &lines[s.start..s.end];
            Chunk {
                ordinal,
                title: truncate_middle(&s.title, 100),
                line_start: s.start + 1,
                line_end: s.end,
                content_type: classify(slice),
                body: slice.join("\n"),
            }
        })
        .collect()
}

// ---------------------------------------------------------------------------------------------
// shared post-pass

fn bytes_of(lines: &[&str], s: &Segment) -> usize {
    lines[s.start..s.end].iter().map(|l| l.len() + 1).sum()
}

/// Fill gaps so segments cover [0, n), drop empties, merge tiny ones (unless `merge_small` is
/// false), split huge ones.
fn normalise(segs: Vec<Segment>, lines: &[&str], merge_small: bool) -> Vec<Segment> {
    let covered = cover_segments(segs, lines);
    let merged = merge_small_segments(covered, lines, merge_small);
    split_large_segments(merged, lines)
}

fn cover_segments(mut segs: Vec<Segment>, lines: &[&str]) -> Vec<Segment> {
    let n = lines.len();
    segs.retain(|s| s.end > s.start && s.start < n);
    segs.sort_by_key(|s| s.start);
    // Make contiguous: each segment runs to the next one's start; first starts at 0.
    let mut covered = Vec::with_capacity(segs.len());
    let mut cursor = 0;
    for (i, s) in segs.iter().enumerate() {
        let start = if i == 0 { 0 } else { s.start.max(cursor) };
        let end = segs
            .get(i + 1)
            .map(|nx| nx.start.max(start))
            .unwrap_or(n)
            .min(n);
        if end > start {
            covered.push(Segment {
                start,
                end,
                title: s.title.clone(),
            });
            cursor = end;
        }
    }
    if covered.is_empty() && n > 0 {
        covered.push(Segment {
            start: 0,
            end: n,
            title: title_for(lines),
        });
    }
    if let Some(last) = covered.last_mut() {
        last.end = n;
    }
    covered
}

fn merge_small_segments(covered: Vec<Segment>, lines: &[&str], merge_small: bool) -> Vec<Segment> {
    // Fold tiny segments into their successor; the bigger side's title wins.
    let mut merged: Vec<Segment> = Vec::with_capacity(covered.len());
    for s in covered {
        match merged.last_mut() {
            Some(prev) if merge_small && bytes_of(lines, prev) < MIN_BYTES => {
                if bytes_of(lines, &s) > bytes_of(lines, prev) {
                    prev.title = s.title;
                }
                prev.end = s.end;
            }
            _ => merged.push(s),
        }
    }
    merged
}

fn split_large_segments(merged: Vec<Segment>, lines: &[&str]) -> Vec<Segment> {
    // Split big segments.
    let mut out = Vec::with_capacity(merged.len());
    for s in merged {
        if bytes_of(lines, &s) <= MAX_BYTES && s.end - s.start <= MAX_LINES {
            out.push(s);
            continue;
        }
        out.extend(split_segment(&s, lines));
    }
    out
}

/// Split at blank lines (paragraph boundaries) accumulating up to the limits; if a single
/// paragraph is itself too large, fall back to fixed windows.
fn split_segment(s: &Segment, lines: &[&str]) -> Vec<Segment> {
    let mut parts: Vec<Segment> = Vec::new();
    let mut start = s.start;
    let mut bytes = 0;
    let mut i = s.start;
    while i < s.end {
        let l = lines[i];
        if i > start && (bytes + l.len() + 1 > MAX_BYTES || i - start >= MAX_LINES) {
            // Prefer cutting just after the most recent blank line, if that leaves a
            // reasonably sized part; otherwise cut here.
            let cut = (start + 1..=i)
                .rev()
                .find(|&k| lines[k - 1].trim().is_empty() && k - start >= MAX_LINES / 4)
                .unwrap_or(i);
            parts.push(Segment {
                start,
                end: cut,
                title: String::new(),
            });
            start = cut;
            bytes = lines[start..i].iter().map(|l| l.len() + 1).sum();
        }
        bytes += l.len() + 1;
        i += 1;
    }
    if start < s.end {
        parts.push(Segment {
            start,
            end: s.end,
            title: String::new(),
        });
    }
    let total = parts.len();
    let base = &s.title;
    for (k, p) in parts.iter_mut().enumerate() {
        p.title = if total > 1 {
            format!("{base} ({}/{total})", k + 1)
        } else {
            s.title.clone()
        };
    }
    parts
}

// ---------------------------------------------------------------------------------------------
// diff

static DIFF_FILE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^diff --git a/(.+?) b/(.+)$").unwrap());
static DIFF_PLUS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\+\+\+ (?:b/)?(\S+)").unwrap());
static DIFF_HUNK: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^@@ .*?@@ ?(.*)$").unwrap());

fn looks_like_diff(lines: &[&str]) -> bool {
    let head = &lines[..lines.len().min(200)];
    let git = head.iter().any(|l| l.starts_with("diff --git "));
    let unified = head.iter().any(|l| l.starts_with("--- "))
        && head.iter().any(|l| l.starts_with("+++ "))
        && head.iter().any(|l| l.starts_with("@@ "));
    git || unified
}

fn diff_segments(lines: &[&str]) -> Vec<Segment> {
    let git = lines.iter().any(|l| l.starts_with("diff --git "));
    let mut segs: Vec<Segment> = Vec::new();
    let mut file = String::new();
    for (i, l) in lines.iter().enumerate() {
        if let Some(c) = DIFF_FILE.captures(l) {
            file = c[2].to_string();
            close(&mut segs, i);
            segs.push(seg(i, &file));
            continue;
        }
        if !git
            && l.starts_with("--- ")
            && lines
                .get(i + 1)
                .map(|n| n.starts_with("+++ "))
                .unwrap_or(false)
        {
            file = DIFF_PLUS
                .captures(lines[i + 1])
                .map(|c| c[1].to_string())
                .unwrap_or_default();
            close(&mut segs, i);
            segs.push(seg(i, &file));
            continue;
        }
        if let Some(c) = DIFF_HUNK.captures(l) {
            // Every hunk starts a segment; the merge pass folds small ones back together so
            // short files stay one chunk while big ones split per hunk.
            let ctx = c[1].trim();
            let title = if ctx.is_empty() {
                file.clone()
            } else {
                format!("{file} — {ctx}")
            };
            close(&mut segs, i);
            segs.push(seg(i, &title));
        }
    }
    close(&mut segs, lines.len());
    segs
}

fn seg(start: usize, title: &str) -> Segment {
    Segment {
        start,
        end: start,
        title: title.to_string(),
    }
}

fn close(segs: &mut [Segment], at: usize) {
    if let Some(last) = segs.last_mut() {
        if last.end < at {
            last.end = at;
        }
    }
}

// ---------------------------------------------------------------------------------------------
// json

fn looks_like_json(text: &str, lines: &[&str]) -> bool {
    let t = text.trim_start();
    if !(t.starts_with('{') || t.starts_with('[')) {
        return false;
    }
    // Cheap structural check before paying for a parse: most lines end like JSON lines do.
    let jsonish = lines
        .iter()
        .filter(|l| !l.trim().is_empty())
        .filter(|l| {
            let t = l.trim_end();
            t.ends_with([',', '{', '[', '}', ']', '"'])
                || t.ends_with("null")
                || t.ends_with("true")
                || t.ends_with("false")
                || t.chars()
                    .last()
                    .map(|c| c.is_ascii_digit())
                    .unwrap_or(false)
        })
        .count();
    let nonblank = lines.iter().filter(|l| !l.trim().is_empty()).count();
    jsonish * 10 >= nonblank * 9 && serde_json::from_str::<serde::de::IgnoredAny>(text).is_ok()
}

/// Line-based walk of pretty-printed JSON, tracking the key path of every line.
struct JsonLine {
    /// Key path of the value starting on this line (e.g. `items[3].labels`), or None for
    /// closing brackets / the root opener.
    path: Option<String>,
    depth: usize,
}

fn json_lines(lines: &[&str]) -> Vec<JsonLine> {
    // (is_array, child_count) per open container; path labels per depth.
    let mut stack: Vec<(bool, usize)> = Vec::new();
    let mut labels: Vec<String> = Vec::new();
    lines
        .iter()
        .map(|line| json_line(line.trim(), &mut stack, &mut labels))
        .collect()
}

fn json_line(t: &str, stack: &mut Vec<(bool, usize)>, labels: &mut Vec<String>) -> JsonLine {
    if t.is_empty() {
        return JsonLine {
            path: None,
            depth: stack.len(),
        };
    }
    if t.starts_with('}') || t.starts_with(']') {
        stack.pop();
        labels.truncate(stack.len().saturating_sub(1));
        return JsonLine {
            path: None,
            depth: stack.len(),
        };
    }
    let depth = stack.len();
    let path = stack.last_mut().map(|(is_array, count)| {
        let label = if *is_array {
            format!("[{count}]")
        } else {
            key_of(t).unwrap_or_else(|| format!("[{count}]"))
        };
        *count += 1;
        labels.truncate(depth - 1);
        labels.push(label);
        join_path(labels)
    });
    let opener = t.trim_end_matches(',');
    if opener.ends_with('{') {
        stack.push((false, 0));
    } else if opener.ends_with('[') {
        stack.push((true, 0));
    }
    JsonLine { path, depth }
}

fn key_of(t: &str) -> Option<String> {
    let rest = t.strip_prefix('"')?;
    let end = rest.find("\":")?;
    Some(rest[..end].to_string())
}

fn join_path(labels: &[String]) -> String {
    let mut s = String::new();
    for l in labels {
        if l.starts_with('[') {
            s.push_str(l);
        } else {
            if !s.is_empty() {
                s.push('.');
            }
            s.push_str(l);
        }
    }
    s
}

fn json_segments(lines: &[&str]) -> Vec<Segment> {
    let info = json_lines(lines);
    let mut segs = Vec::new();
    json_split(lines, &info, 0, lines.len(), 1, &mut segs);
    segs
}

/// Segments for [start, end) using children at `depth`; recurse into oversized ones.
fn json_split(
    lines: &[&str],
    info: &[JsonLine],
    start: usize,
    end: usize,
    depth: usize,
    out: &mut Vec<Segment>,
) {
    let starts: Vec<usize> = (start..end)
        .filter(|&i| info[i].depth == depth && info[i].path.is_some())
        .collect();
    if starts.is_empty() || depth > 6 {
        out.push(json_fallback_segment(lines, info, start, end));
        return;
    }
    // Pack consecutive small siblings into one segment (titled as a range) so an array of
    // 40 small objects doesn't become 40 chunks; recurse only into siblings that are big on
    // their own.
    let mut run: Option<(Segment, String)> = None; // (segment, last label)
    for (k, &s) in starts.iter().enumerate() {
        let seg_start = if k == 0 { start } else { s };
        let seg_end = starts.get(k + 1).copied().unwrap_or(end);
        let label = info[s].path.clone().unwrap_or_default();
        let seg = Segment {
            start: seg_start,
            end: seg_end,
            title: label.clone(),
        };
        let size = bytes_of(lines, &seg);
        let has_children =
            (seg_start..seg_end).any(|i| info[i].depth == depth + 1 && info[i].path.is_some());
        if size > MAX_BYTES && has_children {
            flush_json_run(&mut run, out);
            json_split(lines, info, seg_start, seg_end, depth + 1, out);
            continue;
        }
        append_json_run(&mut run, seg, label, size, lines, out);
    }
    flush_json_run(&mut run, out);
}

fn json_fallback_segment(lines: &[&str], info: &[JsonLine], start: usize, end: usize) -> Segment {
    Segment {
        start,
        end,
        title: info[start..end]
            .iter()
            .find_map(|l| l.path.clone())
            .unwrap_or_else(|| title_for(&lines[start..end])),
    }
}

fn flush_json_run(run: &mut Option<(Segment, String)>, out: &mut Vec<Segment>) {
    if let Some((mut seg, last)) = run.take() {
        if seg.title != last {
            seg.title = range_title(&seg.title, &last);
        }
        out.push(seg);
    }
}

fn append_json_run(
    run: &mut Option<(Segment, String)>,
    seg: Segment,
    label: String,
    size: usize,
    lines: &[&str],
    out: &mut Vec<Segment>,
) {
    match run {
        Some((acc, last)) if bytes_of(lines, acc) + size <= MAX_BYTES => {
            acc.end = seg.end;
            *last = label;
        }
        _ => {
            flush_json_run(run, out);
            *run = Some((seg, label));
        }
    }
}

/// `items[0]` + `items[5]` → `items[0..5]`; `a.x` + `a.z` → `a.x … z`.
fn range_title(first: &str, last: &str) -> String {
    if let (Some(i), Some(j)) = (first.rfind('['), last.rfind('[')) {
        let (a, b) = (&first[i + 1..], &last[j + 1..]);
        let trailing_index =
            |x: &str| x.ends_with(']') && x[..x.len() - 1].chars().all(|c| c.is_ascii_digit());
        if first[..i] == last[..j] && trailing_index(a) && trailing_index(b) {
            return format!(
                "{}[{}..{}]",
                &first[..i],
                &a[..a.len() - 1],
                &b[..b.len() - 1]
            );
        }
    }
    let tail = last.rsplit(['.', '[']).next().unwrap_or(last);
    format!("{first} … {tail}")
}

// ---------------------------------------------------------------------------------------------
// markdown

static HEADING: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^(#{1,6})\s+(.+?)\s*#*\s*$").unwrap());

fn looks_like_markdown(lines: &[&str]) -> bool {
    let mut headings = 0;
    let mut in_fence = false;
    for l in lines {
        if l.trim_start().starts_with("```") {
            in_fence = !in_fence;
            continue;
        }
        if !in_fence && HEADING.is_match(l) {
            headings += 1;
        }
    }
    headings >= 2
}

fn markdown_segments(lines: &[&str]) -> Vec<Segment> {
    let mut segs: Vec<Segment> = Vec::new();
    let mut crumbs: Vec<(usize, String)> = Vec::new();
    let mut in_fence = false;
    for (i, l) in lines.iter().enumerate() {
        if l.trim_start().starts_with("```") {
            in_fence = !in_fence;
            continue;
        }
        if in_fence {
            continue;
        }
        let Some(c) = HEADING.captures(l) else {
            continue;
        };
        let level = c[1].len();
        let text = c[2].trim().to_string();
        crumbs.retain(|(lv, _)| *lv < level);
        crumbs.push((level, text));
        let title = crumbs
            .iter()
            .map(|(_, t)| t.as_str())
            .collect::<Vec<_>>()
            .join(" > ");
        close(&mut segs, i);
        segs.push(seg(i, &title));
    }
    close(&mut segs, lines.len());
    if segs.first().map(|s| s.start > 0).unwrap_or(true) {
        let end = segs.first().map(|s| s.start).unwrap_or(lines.len());
        segs.insert(
            0,
            Segment {
                start: 0,
                end,
                title: title_for(&lines[..end]),
            },
        );
    }
    segs
}

// ---------------------------------------------------------------------------------------------
// test output

static CARGO_TEST: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^test \S+ \.\.\. (ok|FAILED|ignored)").unwrap());
static CARGO_FAIL_BLOCK: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^---- (\S+) (stdout|stderr) ----$").unwrap());
static PYTEST_BLOCK: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^_{3,} (.+?) _{3,}$").unwrap());
static PYTEST_SUMMARY: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^={3,} .*(passed|failed|error|FAILURES|ERRORS|short test summary).* ={3,}$")
        .unwrap()
});
static JEST_BLOCK: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\s*● (.+)$").unwrap());
static JEST_FILE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\s*(PASS|FAIL) (\S+)").unwrap());

fn looks_like_test_output(lines: &[&str]) -> bool {
    let mut score = 0;
    for l in lines {
        if CARGO_TEST.is_match(l) || CARGO_FAIL_BLOCK.is_match(l) {
            score += 1;
        } else if PYTEST_BLOCK.is_match(l) || PYTEST_SUMMARY.is_match(l) {
            score += 2;
        } else if JEST_FILE.is_match(l) || JEST_BLOCK.is_match(l) {
            score += 1;
        }
        if score >= 3 {
            return true;
        }
    }
    false
}

fn test_segments(lines: &[&str]) -> Vec<Segment> {
    let mut segs: Vec<Segment> = Vec::new();
    for (i, l) in lines.iter().enumerate() {
        if let Some(t) = test_section_title(l) {
            close(&mut segs, i);
            segs.push(seg(i, &t));
        }
    }
    close(&mut segs, lines.len());
    segs
}

fn test_section_title(line: &str) -> Option<String> {
    if let Some(c) = CARGO_FAIL_BLOCK.captures(line) {
        return Some(format!("FAIL {}", &c[1]));
    }
    if (line.starts_with("running ") && line.ends_with(" tests"))
        || line.starts_with("running 1 test")
        || line.starts_with("failures:")
        || line.starts_with("test result:")
    {
        return Some(line.to_string());
    }
    if let Some(c) = PYTEST_BLOCK.captures(line) {
        return Some(format!("FAIL {}", &c[1]));
    }
    if PYTEST_SUMMARY.is_match(line) {
        return Some(line.trim_matches(|c| c == '=' || c == ' ').to_string());
    }
    if let Some(c) = JEST_FILE.captures(line) {
        return Some(format!("{} {}", &c[1], &c[2]));
    }
    JEST_BLOCK
        .captures(line)
        .map(|c| format!("● {}", c[1].trim()))
}

// ---------------------------------------------------------------------------------------------
// logs

static LOG_PREFIX: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"(?x)^\s*(
            \[?\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}      # ISO date-time
          | \[?\d{2}:\d{2}:\d{2}                     # bare time
          | \[?\d{10,13}\]?\s                        # epoch
          | \[?(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|PANIC|CRITICAL)\]?[:\s]
          | (error|warning)(\[E\d+\])?:              # rustc / gcc style
        )",
    )
    .unwrap()
});
static LOG_MARKER: LazyLock<Regex> = LazyLock::new(|| {
    // A severity word near the start of the line (after any timestamp / pid / module prefix).
    Regex::new(r"(?i)^.{0,48}?\b(error|warn|warning|fatal|panic|panicked|failed|exception|traceback|critical)\b").unwrap()
});

fn looks_like_log(lines: &[&str]) -> bool {
    let nonblank: Vec<&&str> = lines.iter().filter(|l| !l.trim().is_empty()).collect();
    if nonblank.is_empty() {
        return false;
    }
    let prefixed = nonblank.iter().filter(|l| LOG_PREFIX.is_match(l)).count();
    let markers = nonblank.iter().filter(|l| LOG_MARKER.is_match(l)).count();
    prefixed * 10 >= nonblank.len() * 3 || markers >= 3
}

fn log_segments(lines: &[&str]) -> Vec<Segment> {
    let mut segs: Vec<Segment> = Vec::new();
    let mut run_start = 0;
    let mut prev_marker = false;
    for (i, l) in lines.iter().enumerate() {
        let marker = LOG_MARKER.is_match(l);
        // Cut where an error burst *starts* (a marker after non-marker lines) and when a run
        // gets long; a wall of consecutive error lines stays one run.
        let burst_start = marker && !prev_marker;
        if i > 0 && (burst_start || i - run_start >= FixedWindow::default().lines) {
            close(&mut segs, i);
            segs.push(seg(i, &log_title(l)));
            run_start = i;
        } else if segs.is_empty() {
            segs.push(seg(0, &log_title(l)));
        }
        prev_marker = marker;
    }
    close(&mut segs, lines.len());
    segs
}

/// Title for a log line: drop timestamp / level / host-process prefixes so the message leads.
fn log_title(line: &str) -> String {
    let t = line.trim();
    let mut rest = t;
    for _ in 0..2 {
        if let Some(m) = LOG_PREFIX.find(rest) {
            rest = rest[m.end()..].trim_start();
        } else {
            break;
        }
    }
    // "localhost launchd[1]: message" / "worker: message" → "message".
    if let Some(i) = rest.find(": ") {
        let head = &rest[..i];
        let looks_like_source = head.len() < 40 && (head.ends_with(']') || !head.contains(' '));
        if looks_like_source {
            rest = rest[i + 2..].trim_start();
        }
    }
    if rest.is_empty() {
        t.to_string()
    } else {
        rest.to_string()
    }
}

// ---------------------------------------------------------------------------------------------
// source code

/// A top-level-ish definition line in the common languages: Rust, Python, JS/TS, Go, Java/C#,
/// Ruby, C/C++ (function-looking lines at low indentation). Titles come from these.
static DEFINITION: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"(?x)^(?P<indent>[\x20\t]{0,4})(?:
            (?:pub(?:\([^)]*\))?\s+)?(?:async\s+|unsafe\s+|const\s+|extern\s+\S+\s+)*(?:fn|struct|enum|trait|impl|mod|type|macro_rules!)\s+\S
          | (?:async\s+)?def\s+\w+|class\s+\w+
          | (?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\*?\s+\w+|class\s+\w+|interface\s+\w+|enum\s+\w+|type\s+\w+\s*=|(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>)
          | func\s+(?:\([^)]*\)\s*)?\w+\s*\(
          | (?:(?:public|private|protected|internal|static|final|abstract|override|virtual)\s+)*(?:class|interface|enum|record|struct)\s+\w+
          | (?:(?:public|private|protected|internal|static|final|abstract|override|virtual|synchronized)\s+)+[\w<>\[\],]+\s+\w+\s*\([^;]*$
          | (?:module|describe|context|it|test)\s*\(
          | (?:def|module|class)\s+[A-Z]\w*
        )",
    )
    .unwrap()
});

fn looks_like_code(lines: &[&str]) -> bool {
    classify(lines) == crate::chunk::ContentType::Code
        && lines.iter().filter(|l| DEFINITION.is_match(l)).count() >= 3
}

fn code_segments(lines: &[&str]) -> Vec<Segment> {
    let mut segs: Vec<Segment> = Vec::new();
    for (i, l) in lines.iter().enumerate() {
        if !DEFINITION.is_match(l) {
            continue;
        }
        // Attach doc comments / attributes / decorators directly above the definition.
        let mut start = i;
        while start > 0 {
            let p = lines[start - 1].trim();
            let attached = p.starts_with("///")
                || p.starts_with("//!")
                || p.starts_with("#[")
                || p.starts_with('@')
                || p.starts_with("/**")
                || p.starts_with('*')
                || p.starts_with("\"\"\"")
                || p.starts_with('#') && !p.starts_with("#!");
            if !attached {
                break;
            }
            start -= 1;
        }
        if segs.last().map(|s| start <= s.start).unwrap_or(false) {
            continue;
        }
        close(&mut segs, start);
        segs.push(seg(start, &signature(l)));
    }
    if segs.first().map(|s| s.start > 0).unwrap_or(true) {
        let end = segs.first().map(|s| s.start).unwrap_or(lines.len());
        segs.insert(
            0,
            Segment {
                start: 0,
                end,
                title: title_for(&lines[..end]),
            },
        );
    }
    close(&mut segs, lines.len());
    segs
}

/// `pub fn open(path: &Path) -> Result<Self> {` → `fn open(path: &Path) -> Result<Self>`.
fn signature(line: &str) -> String {
    let t = line.trim().trim_end_matches(['{', ' ']).trim();
    let t = t.strip_suffix("=>").unwrap_or(t).trim();
    let t = t.trim_end_matches([':', '=', ' ']).trim();
    let t = t
        .strip_prefix("export default ")
        .or_else(|| t.strip_prefix("export "))
        .unwrap_or(t);
    let t = t.strip_prefix("pub ").unwrap_or(t);
    let t = match t.find("pub(") {
        Some(0) => t.find(") ").map(|i| &t[i + 2..]).unwrap_or(t),
        _ => t,
    };
    t.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn jsonl_key_can_group_nested_file_fields() {
        let lines = [
            r#"{"location":{"file":"a.rs"},"id":1}"#,
            r#"{"location":{"file":"a.rs"},"id":2}"#,
            r#"{"location":{"file":"b.rs"},"id":3}"#,
        ];
        let segments = jsonl_key_segments("location.file", &lines);
        assert_eq!(segments.len(), 2);
        assert_eq!(segments[0].title, "a.rs");
        assert_eq!(segments[1].title, "b.rs");
    }

    fn chunks(text: &str) -> Vec<Chunk> {
        chunk_with(detect(text), text)
    }

    fn assert_contiguous(text: &str, cs: &[Chunk]) {
        let n = text.lines().count();
        assert_eq!(cs[0].line_start, 1);
        assert_eq!(cs.last().unwrap().line_end, n);
        for w in cs.windows(2) {
            assert_eq!(
                w[0].line_end + 1,
                w[1].line_start,
                "gap/overlap between chunks"
            );
        }
        let lines: Vec<&str> = text.lines().collect();
        for c in cs {
            assert_eq!(c.body, lines[c.line_start - 1..c.line_end].join("\n"));
        }
    }

    #[test]
    fn markdown_breadcrumbs_and_fences() {
        let text = "intro line\n\n# Guide\n\ntext\n\n## Auth\n\n```\n# not a heading\n```\n\n### Tokens\n\nmore\n";
        assert_eq!(detect(text), Strategy::Markdown);
        let segs = markdown_segments(&text.lines().collect::<Vec<_>>());
        let titles: Vec<&str> = segs.iter().map(|s| s.title.as_str()).collect();
        assert_eq!(
            titles,
            [
                "intro line",
                "Guide",
                "Guide > Auth",
                "Guide > Auth > Tokens"
            ]
        );
        let cs = chunks(text);
        assert_contiguous(text, &cs);
    }

    #[test]
    fn markdown_large_section_splits_on_paragraphs() {
        let mut text = String::from("# Big\n\n");
        for i in 0..60 {
            text.push_str(&format!("paragraph {i} {}\n\n", "word ".repeat(30)));
        }
        text.push_str("# Small\n\nend\n");
        let cs = chunks(&text);
        assert_contiguous(&text, &cs);
        assert!(cs.len() >= 3, "{}", cs.len());
        assert!(cs[0].title.starts_with("Big (1/"), "{}", cs[0].title);
        for c in &cs {
            assert!(c.body.len() <= MAX_BYTES + 200, "{} bytes", c.body.len());
        }
        assert_eq!(cs.last().unwrap().title, "Small");
    }

    #[test]
    fn json_key_paths() {
        let v = serde_json::json!({
            "name": "x",
            "items": (0..40).map(|i| serde_json::json!({"id": i, "labels": ["a", "b", "c"], "desc": "d".repeat(60)})).collect::<Vec<_>>(),
            "meta": {"count": 40, "next": null}
        });
        let text = serde_json::to_string_pretty(&v).unwrap();
        assert_eq!(detect(&text), Strategy::Json);
        let cs = chunks(&text);
        assert_contiguous(&text, &cs);
        let titles: Vec<&str> = cs.iter().map(|c| c.title.as_str()).collect();
        assert!(titles.iter().any(|t| t.starts_with("items[")), "{titles:?}");
        assert!(
            titles
                .iter()
                .any(|t| t.starts_with("meta") || t.starts_with("items[3")),
            "{titles:?}"
        );
        for c in &cs {
            assert!(
                c.body.len() <= MAX_BYTES + 200,
                "{} bytes: {}",
                c.body.len(),
                c.title
            );
        }
    }

    #[test]
    fn range_titles() {
        assert_eq!(range_title("items[0]", "items[5]"), "items[0..5]");
        assert_eq!(
            range_title("p[0].dependencies[2]", "p[0].dependencies[9]"),
            "p[0].dependencies[2..9]"
        );
        assert_eq!(
            range_title("p[0].description", "p[0].version"),
            "p[0].description … version"
        );
        assert_eq!(
            range_title("resolve", "workspace_root"),
            "resolve … workspace_root"
        );
    }

    #[test]
    fn json_path_labels() {
        let text = "{\n  \"a\": {\n    \"b\": [\n      {\n        \"c\": 1\n      }\n    ]\n  }\n}";
        let lines: Vec<&str> = text.lines().collect();
        let info = json_lines(&lines);
        let paths: Vec<Option<&str>> = info.iter().map(|l| l.path.as_deref()).collect();
        assert_eq!(
            paths,
            [
                None,
                Some("a"),
                Some("a.b"),
                Some("a.b[0]"),
                Some("a.b[0].c"),
                None,
                None,
                None,
                None
            ]
        );
    }

    #[test]
    fn diff_per_file_with_hunks() {
        let mut text = String::new();
        for f in ["src/a.rs", "src/b.rs"] {
            text.push_str(&format!(
                "diff --git a/{f} b/{f}\nindex 1..2 100644\n--- a/{f}\n+++ b/{f}\n"
            ));
            for h in 0..3 {
                text.push_str(&format!("@@ -{h}0,4 +{h}0,5 @@ fn hunk{h}()\n"));
                for i in 0..30 {
                    text.push_str(&format!("+    line {i} in {f} hunk {h}\n"));
                }
            }
        }
        assert_eq!(detect(&text), Strategy::Diff);
        let cs = chunks(&text);
        assert_contiguous(&text, &cs);
        let titles: Vec<&str> = cs.iter().map(|c| c.title.as_str()).collect();
        // The 4-line file header is folded into its first hunk.
        assert_eq!(titles[0], "src/a.rs — fn hunk0()");
        assert!(
            titles.iter().any(|t| t.starts_with("src/b.rs — fn hunk1")),
            "{titles:?}"
        );
    }

    #[test]
    fn cargo_test_output_per_failure() {
        let mut text = String::from("   Compiling x\n     Running tests\n\nrunning 3 tests\ntest a ... ok\ntest b ... FAILED\ntest c ... ok\n\nfailures:\n\n---- b stdout ----\n");
        for i in 0..20 {
            text.push_str(&format!("assertion detail line {i}\n"));
        }
        text.push_str("\nfailures:\n    b\n\ntest result: FAILED. 2 passed; 1 failed\n");
        assert_eq!(detect(&text), Strategy::Test);
        let cs = chunks(&text);
        assert_contiguous(&text, &cs);
        let titles: Vec<&str> = cs.iter().map(|c| c.title.as_str()).collect();
        assert!(titles.contains(&"FAIL b"), "{titles:?}");
    }

    #[test]
    fn pytest_and_jest_detected() {
        let py = "============ FAILURES ============\n____________ test_login ____________\n\n    def test_login():\n>       assert 1 == 2\nE       assert 1 == 2\n\n====== 1 failed, 3 passed in 0.2s ======\n";
        assert_eq!(detect(py), Strategy::Test);
        let jest = "PASS src/a.test.ts\nFAIL src/b.test.ts\n  ● Suite › does thing\n\n    expect(received).toBe(expected)\n\n  ● Suite › other thing\n\n    boom\n";
        assert_eq!(detect(jest), Strategy::Test);
        let cs = chunks(jest);
        assert_contiguous(jest, &cs);
    }

    #[test]
    fn log_cuts_at_markers() {
        let mut text = String::new();
        for i in 0..50 {
            let lvl = if i % 20 == 10 { "ERROR" } else { "INFO" };
            text.push_str(&format!(
                "2026-09-22T10:00:{i:02}Z {lvl} worker: step {i} {}\n",
                "detail ".repeat(10)
            ));
        }
        assert_eq!(detect(&text), Strategy::Log);
        let cs = chunks(&text);
        assert_contiguous(&text, &cs);
        assert!(
            cs.iter().any(|c| c.title.contains("ERROR")),
            "{:?}",
            cs.iter().map(|c| &c.title).collect::<Vec<_>>()
        );
        assert!(cs.len() >= 2);
    }

    #[test]
    fn source_files_split_at_definitions() {
        let text = "//! crate docs\nuse std::fs;\n\n/// Opens it.\n#[inline]\npub fn open(path: &str) -> Result<()> {\n    let x = 1;\n    Ok(())\n}\n\npub(crate) struct Store {\n    conn: Connection,\n}\n\nimpl Store {\n    pub fn close(&self) {\n        drop(self);\n    }\n}\n\nfn helper() -> u8 {\n    3\n}\n";
        assert_eq!(detect(text), Strategy::Code);
        let segs = code_segments(&text.lines().collect::<Vec<_>>());
        let titles: Vec<&str> = segs.iter().map(|s| s.title.as_str()).collect();
        assert_eq!(
            titles,
            [
                "//! crate docs",
                "fn open(path: &str) -> Result<()>",
                "struct Store",
                "impl Store",
                "fn close(&self)",
                "fn helper() -> u8"
            ],
            "{titles:?}"
        );
        // Doc comment and attribute travel with the definition.
        assert_eq!(segs[1].start, 3);
        let cs = chunks(text);
        assert_contiguous(text, &cs);

        let py = "import os\n\nclass Widget:\n    def __init__(self):\n        pass\n\n    def run(self, x):\n        return x\n\ndef main():\n    Widget().run(1)\n";
        let segs = code_segments(&py.lines().collect::<Vec<_>>());
        let titles: Vec<&str> = segs.iter().map(|s| s.title.as_str()).collect();
        assert_eq!(
            titles,
            [
                "import os",
                "class Widget",
                "def __init__(self)",
                "def run(self, x)",
                "def main()"
            ],
            "{titles:?}"
        );

        let ts = "import x from 'y';\n\nexport async function fetchAll(url: string) {\n  return 1;\n}\n\nexport const parse = (s: string) => {\n  return s;\n};\n\nexport class Client {\n  get() {}\n}\n";
        let segs = code_segments(&ts.lines().collect::<Vec<_>>());
        let titles: Vec<&str> = segs.iter().map(|s| s.title.as_str()).collect();
        assert_eq!(
            titles,
            [
                "import x from 'y';",
                "async function fetchAll(url: string)",
                "const parse = (s: string)",
                "class Client"
            ],
            "{titles:?}"
        );
    }

    #[test]
    fn plain_text_falls_back() {
        let text = (0..200)
            .map(|i| format!("plain line {i}\n"))
            .collect::<String>();
        assert_eq!(detect(&text), Strategy::Fixed);
        let cs = chunks(&text);
        assert_eq!(cs[0].line_start, 1);
        assert_eq!(cs.last().unwrap().line_end, 200);
    }
}
