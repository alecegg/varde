//! Scan one Markdown file for pointers to the skill's other files and for
//! external calls (inline skill modes and agent dispatches).
//!
//! Rules are text heuristics over a block (a paragraph, list item, table row
//! or fenced line), its sentence (text up to `. ! ?`) and its clause (also
//! ending at `;`). Backticked spans are blanked when matching words, keeping
//! offsets, so all positions are byte offsets into the block's text.

use super::{EdgeKind, External, ExternalType, Runs};
use fancy_regex::{Match, Regex};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

type Captures<'t> = fancy_regex::Captures<'t, str>;

macro_rules! pattern {
    ($name:ident, $source:expr) => {
        pub(super) static $name: LazyLock<Regex> =
            LazyLock::new(|| Regex::new($source).expect("flow patterns are valid"));
    };
}

pattern!(SPAN, r"`([^`\n]+)`");
pattern!(SECTION, r"`#{1,6}\s+([^`]+)`");
// Lookbehind: a path starts the span or follows whitespace, `/` or `(`.
pattern!(
    PATH,
    r#"(?:^|(?<=[\s/(]))((?:references|scripts|assets)/[^\s`)\]'",;]+)"#
);
pattern!(SCRIPT, r#"(?:^|(?<=[\s/(]))(scripts/[^\s`)\]'",;]+)"#);
pattern!(LINK, r"\]\(([^)\s]+)[^)]*\)");
pattern!(HEADING, r"^(#{1,6})\s+(.*)");
pattern!(NUMBERED, r"^\d+[.)]?\s");
pattern!(STEP, r"^(\d+)[.)]\s+(.*)");
pattern!(ITEM, r"^\s*([-*+]|\d+[.)])\s+");
pattern!(
    LABEL,
    r"^\s*[-*+]\s+(?:\*\*[^*]{1,60}\*\*|`[^`]{1,60}`:|[A-Za-z](?:[^:`*]|`[^`\n]*`){0,99}:(?:\s|$))"
);
// Lookahead: a sentence ends at punctuation followed by whitespace.
pattern!(END, r"[.!?](?=\s)");
pattern!(CLAUSE, r"[.;!?](?=\s)");
pattern!(
    CONDITION,
    r"(?i)\b(if|when|whenever|unless|otherwise|whether)\b|\bonly (?:as|for|after|during|in|on)\b|→|->"
);
pattern!(
    CASE,
    r"(?i)\b(unmerged|separate|isolated|standalone|fallback|failure|failed|stale)\b"
);
// Negative lookahead: "instead of" is not a hand-off.
pattern!(
    HANDOFF,
    r"(?i)\bthen (?:continue|proceed|return|go|move|hand)|\bcontinue (?:with|per|in|at|to)\b|\bnext:|\bhand(?:s|ed)? (?:it )?off\b|\brecommend|\bresume (?:a|an|it|planning|work)\b|\binstead\b(?!\s+of)"
);
pattern!(
    LOAD,
    r"(?i)\b(read|reads|load|loads|loaded|follow|follows|apply|applies|run|runs|see|use|uses|open|opens|per)\b|→|->"
);
pattern!(
    MODE,
    r"^(varde-[a-z][a-z0-9-]*)\s+([a-z][a-z0-9_-]*)(?:\s.*)?$"
);
pattern!(SKILL_NAME, r"^varde-[a-z][a-z0-9-]*$");
pattern!(MODE_WORD, r"^\s+([a-z][a-z0-9_-]*)\b");
pattern!(
    DISPATCH,
    r"(?i)\b(?:dispatch|delegat|spawn|launch)\w*|\bbrief(?:s|ed)? (?:the|an?|each)\b|\bgive an agent\b"
);
pattern!(
    AGENT,
    r"(?i)\b(builder|reviewer|review agent|independent agent|an agent)s?\b"
);
pattern!(
    EDITS,
    r"(?i)\bbefore (?:\w+ )?(?:edit|edits|editing|changes)\b"
);
pattern!(
    ROLE,
    r"(?i)^\W*(?:\d+[.)]\s*)?(?:the|a|an|each)?\s*(?:gate\s+)?(?:reviewer|builder)s?\b|\bas an? (?:independent |gate )?reviewer\b|\b(?:reviewer|builder)s? (?:follows|loads|reads)\b"
);
pattern!(
    ROLE_HEADING,
    r"(?i)^(?:the |as (?:an? |the )?)?(?:gate )?(?:builder|reviewer)s?\b"
);
pattern!(
    OPENING,
    r"(?i)^\W*(?:\d+[.)]\s*)?(?:with|without|for|on|after) (?:a|an|each|no|any)\b"
);
pattern!(REVIEWED, r"(?i)\b(independent|reviewer)\b");
// "dispatch one builder for `references/x.md`"
pattern!(RUNS, r"(?i)\bfor\s*$");
pattern!(ROUTE_WORD, r"(?i)\b(?:route|section)\b");
pattern!(QUALIFIER_WORD, r"(?i)[a-z0-9]+(?:-[a-z0-9]+)*");
pattern!(SCHEME, r"^[A-Za-z][\w+.-]*:");

const ENTRY_ROUTING: &str = "Entry routing";
const STOP_WORDS: [&str; 15] = [
    "and", "but", "or", "then", "to", "for", "with", "from", "before", "after", "when", "while",
    "unless", "because", "route",
];
const IGNORED_QUALIFIERS: [&str; 10] = [
    "and", "follow", "its", "the", "a", "an", "via", "through", "using", "use",
];
const KIND_MARKER: &str = "<!-- kind: reference -->";

// ---- Text helpers ---------------------------------------------------------

pub(super) fn matches(pattern: &Regex, text: &str) -> bool {
    pattern.is_match(text).unwrap_or(false)
}

pub(super) fn search<'t>(pattern: &Regex, text: &'t str) -> Option<Match<'t>> {
    pattern.find(text).ok().flatten()
}

pub(super) fn find_all<'t>(pattern: &Regex, text: &'t str) -> Vec<Captures<'t>> {
    pattern.captures_iter(text).flatten().collect()
}

fn floor_boundary(text: &str, index: usize) -> usize {
    let mut index = index.min(text.len());
    while !text.is_char_boundary(index) {
        index -= 1;
    }
    index
}

/// `text[start..stop]`, clamped to the text and to character boundaries.
pub(super) fn slice(text: &str, start: usize, stop: usize) -> &str {
    let (start, stop) = (floor_boundary(text, start), floor_boundary(text, stop));
    if start >= stop {
        ""
    } else {
        &text[start..stop]
    }
}

fn sentence_end(text: &str, pos: usize, end: &Regex) -> usize {
    let pos = floor_boundary(text, pos);
    match end.find_from_pos(text, pos) {
        Ok(Some(found)) => found.start() + 1,
        _ => text.len(),
    }
}

/// Start and stop of the sentence (or clause) holding `pos`.
pub(super) fn bounds(text: &str, pos: usize, end: &Regex) -> (usize, usize) {
    let before = slice(text, 0, pos);
    let start = end
        .find_iter(before)
        .flatten()
        .map(|found| found.end())
        .max()
        .unwrap_or(0);
    (start, sentence_end(text, pos, end))
}

fn sentence_at<'t>(text: &'t str, pos: usize, end: &Regex) -> &'t str {
    let (start, stop) = bounds(text, pos, end);
    slice(text, start, stop)
}

/// Shorten to `limit` characters after dropping backticks and bold markers.
pub(super) fn short_to(text: &str, limit: usize) -> String {
    let text = text.replace('`', "").replace("**", "");
    let text = text.trim();
    if text.chars().count() <= limit {
        return text.to_string();
    }
    let cut: String = text.chars().take(limit.saturating_sub(3)).collect();
    format!("{}...", cut.trim_end())
}

pub(super) fn short(text: &str) -> String {
    short_to(text, 60)
}

/// Blank out backticked spans, keeping offsets.
pub(super) fn plain(text: &str) -> String {
    SPAN.replace_all(text, |caps: &fancy_regex::Captures<'_, str>| {
        " ".repeat(caps[0].len())
    })
    .into_owned()
}

fn first_nonempty<'a>(row: Option<&'a str>, step: Option<&'a str>, heading: &'a str) -> &'a str {
    [row, step]
        .into_iter()
        .flatten()
        .find(|text| !text.is_empty())
        .unwrap_or(heading)
}

// ---- Files ----------------------------------------------------------------

/// Read a file as text; invalid bytes become U+FFFD and newlines are
/// normalized. A missing file reads as empty.
pub(super) fn read_text(path: &Path) -> String {
    let bytes = fs::read(path).unwrap_or_default();
    String::from_utf8_lossy(&bytes)
        .replace("\r\n", "\n")
        .replace('\r', "\n")
}

/// Estimated tokens of a whole file: one per four characters, rounded up.
pub(super) fn tokens(path: &Path) -> usize {
    read_text(path).chars().count().div_ceil(4)
}

/// True when the file's first line is exactly the reference kind marker.
pub(super) fn is_reference(path: &Path) -> bool {
    read_text(path).split('\n').next() == Some(KIND_MARKER)
}

pub(super) fn file_name(path: &Path) -> String {
    path.file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_default()
}

/// A skill directory and the shared files its siblings' MANIFEST lists for it.
pub(super) struct SkillDir {
    pub dir: PathBuf,
    pub name: String,
    manifest: HashMap<String, HashSet<String>>,
}

impl SkillDir {
    pub fn new(dir: &Path) -> Self {
        let manifest = dir
            .parent()
            .map(|parent| parent.join("shared").join("MANIFEST"))
            .map(|path| read_manifest(&path))
            .unwrap_or_default();
        SkillDir {
            dir: dir.to_path_buf(),
            name: file_name(dir),
            manifest,
        }
    }

    pub fn shared_dir(&self) -> PathBuf {
        self.dir.parent().unwrap_or(&self.dir).join("shared")
    }

    /// Shared files listed for this skill that are not already `files`, sorted.
    pub fn shared_files(&self, files: &[String]) -> Vec<String> {
        let mut shared: Vec<String> = self
            .manifest
            .iter()
            .filter(|(rel, skills)| skills.contains(&self.name) && !files.contains(rel))
            .map(|(rel, _)| rel.clone())
            .collect();
        shared.sort();
        shared
    }

    /// The file `rel` points to: in the skill, else the shared copy listed for it.
    pub fn actual_path(&self, rel: &str) -> PathBuf {
        let local = self.dir.join(rel);
        let listed = self
            .manifest
            .get(rel)
            .is_some_and(|skills| skills.contains(&self.name));
        if !local.is_file() && listed {
            return self.shared_dir().join(rel);
        }
        local
    }

    pub fn read(&self, rel: &str) -> String {
        read_text(&self.actual_path(rel))
    }
}

fn read_manifest(path: &Path) -> HashMap<String, HashSet<String>> {
    let mut manifest = HashMap::new();
    for line in read_text(path).lines() {
        let mut parts = line.split_whitespace();
        if let Some(rel) = parts.next() {
            manifest.insert(rel.to_string(), parts.map(str::to_string).collect());
        }
    }
    manifest
}

fn normpath(path: &str) -> String {
    let absolute = path.starts_with('/');
    let mut parts: Vec<&str> = Vec::new();
    for part in path.split('/') {
        match part {
            "" | "." => {}
            ".." if parts.last().is_some_and(|last| *last != "..") => {
                parts.pop();
            }
            ".." if absolute => {}
            _ => parts.push(part),
        }
    }
    let joined = parts.join("/");
    match (absolute, joined.is_empty()) {
        (true, _) => format!("/{joined}"),
        (false, true) => ".".to_string(),
        (false, false) => joined,
    }
}

// ---- Pointers -------------------------------------------------------------

/// A pointer found on one line: raw target text, whether it is a Markdown
/// link, and its byte column.
pub(super) struct Target {
    pub raw: String,
    pub is_link: bool,
    pub col: usize,
}

/// Every pointer on one line.
pub(super) fn targets(line: &str, fenced: bool) -> Vec<Target> {
    let mut found = Vec::new();
    if fenced {
        for caps in find_all(&SCRIPT, line) {
            found.push(path_target(&caps, 0));
        }
        return found;
    }
    let mut spans: Vec<(&str, usize)> = find_all(&SPAN, line)
        .iter()
        .filter_map(|caps| caps.get(1).map(|m| (m.as_str(), m.start())))
        .collect();
    if line.matches('`').count() % 2 == 1 {
        let cut = line.rfind('`').map_or(0, |at| at + 1);
        spans.push((&line[cut..], cut)); // a span that wraps to the next line
    }
    for (span, start) in spans {
        for caps in find_all(&PATH, span) {
            found.push(path_target(&caps, start));
        }
    }
    for caps in find_all(&LINK, &plain(line)) {
        let Some(link) = caps.get(1) else { continue };
        let text = link.as_str();
        if !text.starts_with(['#', '/', '<']) && !matches(&SCHEME, text) {
            found.push(Target {
                raw: text.to_string(),
                is_link: true,
                col: link.start(),
            });
        }
    }
    found
}

fn path_target(caps: &Captures<'_>, base: usize) -> Target {
    let path = caps.get(1).expect("pattern has a path group");
    Target {
        raw: path.as_str().to_string(),
        is_link: false,
        col: base + path.start(),
    }
}

/// The skill-relative path a pointer names, and whether to skip it
/// (placeholders and directories). A name that exists nowhere is returned
/// unskipped so the caller can report it missing.
pub(super) fn resolve(
    dir: &SkillDir,
    source: &str,
    raw: &str,
    is_link: bool,
) -> (Option<String>, bool) {
    let target = raw
        .split('#')
        .next()
        .unwrap_or("")
        .trim_end_matches(['.', ':']);
    if target.is_empty() || target.ends_with('/') || target.contains(['<', '>', '*', '{', '}', '$'])
    {
        return (None, true);
    }
    let parts: Vec<&str> = source.split('/').collect();
    let folders = &parts[..parts.len() - 1];
    let depths: Vec<usize> = if is_link {
        vec![folders.len()]
    } else {
        (0..=folders.len()).rev().collect()
    };
    let mut first: Option<String> = None;
    for depth in depths {
        let joined = match depth {
            0 => target.to_string(),
            _ => format!("{}/{target}", folders[..depth].join("/")),
        };
        let rel = normpath(&joined);
        if rel.starts_with("..") {
            continue;
        }
        if dir.actual_path(&rel).is_file() {
            return (Some(rel), false);
        }
        first.get_or_insert(rel);
    }
    let skip = first.is_none();
    (first, skip)
}

// ---- Blocks ---------------------------------------------------------------

pub(super) struct BlockLine {
    pub n: usize,
    pub text: String,
    pub step: Option<String>,
}

/// A paragraph, list item, table row or fenced line.
pub(super) struct Block {
    pub lines: Vec<BlockLine>,
    pub heading: String,
    pub case: bool,
    pub role: bool,
    pub table: bool,
    pub fenced: bool,
}

struct Head {
    level: usize,
    case: bool,
    role: bool,
}

fn numbered_levels(lines: &[&str]) -> HashSet<usize> {
    let mut numbered = HashSet::new();
    for &line in lines {
        let Ok(Some(caps)) = HEADING.captures(line.trim()) else {
            continue;
        };
        if caps[1].len() > 1 && matches(&NUMBERED, &caps[2]) {
            numbered.insert(caps[1].len());
        }
    }
    numbered
}

fn heading_is_case(level: usize, text: &str, numbered: &HashSet<usize>) -> bool {
    level > 1
        && (matches(&CONDITION, &plain(text))
            || matches(&CASE, text)
            || (numbered.contains(&level) && !matches(&NUMBERED, text)))
}

/// Group lines into paragraphs, list items, table rows and fenced lines.
pub(super) fn blocks(lines: &[&str]) -> Vec<Block> {
    let numbered = numbered_levels(lines);
    let mut out: Vec<Block> = Vec::new();
    let mut heads: Vec<Head> = Vec::new();
    let mut heading = "(top)".to_string();
    let mut step: Option<String> = None;
    let mut fenced = false;
    let mut current: Option<usize> = None;
    for (index, &line) in lines.iter().enumerate() {
        let n = index + 1;
        let stripped = line.trim();
        if stripped.starts_with("```") || stripped.starts_with("~~~") {
            fenced = !fenced;
            current = None;
            continue;
        }
        let case = heads.iter().any(|head| head.case);
        let role = heads.iter().any(|head| head.role);
        let block_line = |step: &Option<String>| BlockLine {
            n,
            text: line.to_string(),
            step: step.clone(),
        };
        if fenced {
            out.push(Block {
                lines: vec![block_line(&step)],
                heading: heading.clone(),
                case,
                role,
                table: false,
                fenced: true,
            });
            continue;
        }
        if let Ok(Some(caps)) = HEADING.captures(stripped) {
            let (level, text) = (caps[1].len(), &caps[2]);
            heads.retain(|head| head.level < level);
            heads.push(Head {
                level,
                case: heading_is_case(level, text, &numbered),
                role: matches(&ROLE_HEADING, text),
            });
            heading = short(text);
            step = None;
            current = None;
            continue;
        }
        let table = stripped.starts_with('|');
        if stripped.is_empty() || table || matches(&ITEM, line) {
            current = None;
        }
        if let Ok(Some(caps)) = STEP.captures(line) {
            step = Some(format!(
                "{heading} / step {}: {}",
                &caps[1],
                short_to(&caps[2], 40)
            ));
        } else if !stripped.is_empty() && !line.starts_with(char::is_whitespace) && !table {
            step = None;
        }
        if stripped.is_empty() {
            continue;
        }
        let at = *current.get_or_insert_with(|| {
            out.push(Block {
                lines: Vec::new(),
                heading: heading.clone(),
                case,
                role,
                table,
                fenced: false,
            });
            out.len() - 1
        });
        out[at].lines.push(block_line(&step));
        if table {
            current = None;
        }
    }
    out
}

// ---- Scan -----------------------------------------------------------------

/// A pointer to another file of the skill.
pub(super) struct Pointer {
    pub to: String,
    pub raw: String,
    pub context: String,
    pub conditional: bool,
    pub kind: EdgeKind,
    pub table: bool,
    pub line: usize,
}

pub(super) enum Body {
    Pointer(Pointer),
    External(External),
}

/// One scan result with the heading it sits under and whether its sentence
/// is an edit gate ("before edits").
pub(super) struct Scanned {
    pub section: String,
    pub edits: bool,
    pub body: Body,
}

/// A dispatch under construction, keyed by its sentence bounds.
struct Draft {
    span: (i64, i64),
    external: External,
    edits: bool,
}

fn new_external(kind: ExternalType, target: String, context: &str, line: usize) -> External {
    External {
        from: String::new(),
        external: kind,
        target,
        skill: String::new(),
        mode: String::new(),
        runs: None,
        context: context.to_string(),
        conditional: false,
        kind: EdgeKind::Mention,
        table: false,
        line,
        qualifier: None,
        route: None,
        report_order: false,
    }
}

/// Everything the rules need to know about one block.
struct BlockScan<'a> {
    source: &'a str,
    block: &'a Block,
    text: String,
    flat: String,
    bare: String,
    starts: Vec<isize>,
    labeled: bool,
    row: Option<String>,
}

impl<'a> BlockScan<'a> {
    fn new(source: &'a str, block: &'a Block) -> Self {
        let mut text = String::new();
        let mut starts = Vec::new();
        for line in &block.lines {
            let indent = line.text.len() - line.text.trim_start().len();
            starts.push(text.len() as isize - indent as isize);
            text.push_str(line.text.trim());
            text.push(' ');
        }
        let first = block.lines[0].text.trim();
        let row = block
            .table
            .then(|| short(first.trim_matches('|').split('|').next().unwrap_or("")));
        BlockScan {
            source,
            block,
            flat: plain(&text),
            bare: text.replace('`', " "),
            labeled: matches(&LABEL, &text),
            text,
            starts,
            row,
        }
    }

    fn position(&self, offset: isize, col: usize) -> usize {
        (offset + col as isize).max(0) as usize
    }

    fn context(&self, step: Option<&str>) -> String {
        first_nonempty(self.row.as_deref(), step, &self.block.heading).to_string()
    }

    /// The kind of pointer at `pos` and whether it is conditional.
    fn classify(&self, pos: usize) -> (EdgeKind, bool) {
        let block = self.block;
        let skill_md = self.source == "SKILL.md";
        let clause = sentence_at(&self.flat, pos, &CLAUSE);
        if block.table && !skill_md && matches(&HANDOFF, clause) {
            return (EdgeKind::Handoff, true);
        }
        if block.fenced || block.table {
            return (EdgeKind::Load, block.table && !skill_md);
        }
        let sentence = sentence_at(&self.flat, pos, &END);
        let kind = if skill_md && block.heading == ENTRY_ROUTING {
            EdgeKind::Handoff // the request leaves this skill; adds nothing
        } else if block.role || matches(&ROLE, sentence) || matches(&ROLE, clause) {
            EdgeKind::Role // a subagent's load, counted in its dispatch
        } else if matches(&HANDOFF, clause) {
            EdgeKind::Handoff
        } else if matches(&LOAD, sentence) {
            EdgeKind::Load
        } else {
            EdgeKind::Mention
        };
        let upto = slice(&self.flat, 0, sentence_end(&self.flat, pos, &CLAUSE));
        let conditional =
            block.case || self.labeled || matches(&OPENING, sentence) || matches(&CONDITION, upto);
        (kind, conditional)
    }

    fn edits(&self, pos: usize) -> bool {
        !self.block.fenced && matches(&EDITS, sentence_at(&self.flat, pos, &END))
    }

    /// Agent dispatches: an agent word in a sentence with a dispatch word.
    fn find_dispatches(&self) -> Vec<Draft> {
        let mut drafts: Vec<Draft> = Vec::new();
        for caps in find_all(&AGENT, &self.bare) {
            let whole = caps.get(0).expect("whole match");
            let (start, stop) = bounds(&self.bare, whole.start(), &END);
            let span = (start as i64, stop as i64);
            if drafts.iter().any(|d| d.span == span)
                || !matches(&DISPATCH, slice(&self.bare, start, stop))
            {
                continue;
            }
            let at = self
                .starts
                .iter()
                .rposition(|s| *s <= whole.start() as isize)
                .unwrap_or(0);
            let line = &self.block.lines[at];
            let target = if caps[1].eq_ignore_ascii_case("builder") {
                "builder"
            } else {
                "review"
            };
            let mut external = new_external(
                ExternalType::Agent,
                target.to_string(),
                &self.context(line.step.as_deref()),
                line.n,
            );
            external.conditional = self.classify(whole.start()).1;
            external.table = self.block.table;
            drafts.push(Draft {
                span,
                external,
                edits: self.edits(whole.start()),
            });
        }
        drafts
    }
}

fn dispatch_at(drafts: &[Draft], pos: usize) -> Option<usize> {
    drafts
        .iter()
        .position(|d| d.span.0 <= pos as i64 && (pos as i64) < d.span.1)
}

/// Yield internal pointers and external calls for one Markdown file.
pub(super) fn scan(dir: &SkillDir, source: &str, skill_names: &HashSet<String>) -> Vec<Scanned> {
    let text = dir.read(source);
    let lines: Vec<&str> = text.split('\n').collect();
    let mut out = Vec::new();
    for block in blocks(&lines) {
        out.extend(scan_block(dir, source, skill_names, &block));
    }
    out
}

fn scan_block(
    dir: &SkillDir,
    source: &str,
    skill_names: &HashSet<String>,
    block: &Block,
) -> Vec<Scanned> {
    let scan = BlockScan::new(source, block);
    let mut drafts = if block.fenced {
        Vec::new()
    } else {
        scan.find_dispatches()
    };
    let mut out = Vec::new();
    for (line, &offset) in block.lines.iter().zip(&scan.starts) {
        let context = scan.context(line.step.as_deref());
        for target in targets(&line.text, block.fenced) {
            let (rel, skip) = resolve(dir, source, &target.raw, target.is_link);
            let Some(rel) = rel.filter(|rel| !skip && rel != source) else {
                continue;
            };
            let pos = scan.position(offset, target.col);
            if let Some(owner) = dispatch_at(&drafts, pos) {
                let before = slice(&scan.text, 0, pos.saturating_sub(1));
                if drafts[owner].external.runs.is_none() && matches(&RUNS, before) {
                    drafts[owner].external.runs = Some(Runs::File { file: rel.clone() });
                }
            }
            let (kind, conditional) = scan.classify(pos);
            out.push(Scanned {
                section: block.heading.clone(),
                edits: scan.edits(pos),
                body: Body::Pointer(Pointer {
                    to: rel,
                    raw: target.raw,
                    context: context.clone(),
                    conditional,
                    kind,
                    table: block.table,
                    line: line.n,
                }),
            });
        }
        if !block.fenced {
            scan_skill_calls(
                &scan,
                skill_names,
                line,
                offset,
                &context,
                &mut drafts,
                &mut out,
            );
        }
    }
    out.extend(drafts.into_iter().map(|draft| Scanned {
        section: block.heading.clone(),
        edits: draft.edits,
        body: Body::External(draft.external),
    }));
    out
}

/// A `varde-<skill> <mode>` span, or a backticked skill followed by a mode.
struct SkillCall {
    skill: String,
    mode: String,
    mode_end: usize,
}

fn skill_call(line: &str, span: &Captures<'_>, offset: isize) -> Option<SkillCall> {
    let content = span.get(1).expect("span content");
    let base = offset + content.start() as isize;
    if let Ok(Some(call)) = MODE.captures(content.as_str()) {
        let end = call.get(2).expect("mode group").end() as isize;
        return Some(SkillCall {
            skill: call[1].to_string(),
            mode: call[2].to_string(),
            mode_end: (base + end).max(0) as usize,
        });
    }
    if !matches(&SKILL_NAME, content.as_str()) {
        return None;
    }
    let whole_end = span.get(0).expect("whole match").end();
    let following = MODE_WORD.captures(&line[whole_end..]).ok().flatten()?;
    let mode = following.get(1).expect("mode group");
    if STOP_WORDS.contains(&mode.as_str()) {
        return None;
    }
    Some(SkillCall {
        skill: content.as_str().to_string(),
        mode: mode.as_str().to_string(),
        mode_end: (offset + (whole_end + mode.end()) as isize).max(0) as usize,
    })
}

/// The words before "route" or "section" in the rest of a sentence, which
/// qualify which route a mode means.
fn qualifier_of(tail: &str) -> Option<String> {
    let route_word = search(&ROUTE_WORD, tail)?;
    let words: Vec<String> = find_all(&QUALIFIER_WORD, &tail[..route_word.start()])
        .iter()
        .map(|caps| caps[0].to_lowercase())
        .filter(|word| !IGNORED_QUALIFIERS.contains(&word.as_str()))
        .collect();
    (!words.is_empty()).then(|| words.join(" "))
}

fn scan_skill_calls(
    scan: &BlockScan,
    skill_names: &HashSet<String>,
    line: &BlockLine,
    offset: isize,
    context: &str,
    drafts: &mut Vec<Draft>,
    out: &mut Vec<Scanned>,
) {
    for span in find_all(&SPAN, &line.text) {
        let Some(call) = skill_call(&line.text, &span, offset) else {
            continue;
        };
        if !skill_names.is_empty() && !skill_names.contains(&call.skill) {
            continue;
        }
        let pos = scan.position(offset, span.get(0).expect("whole match").start());
        let mut owner = dispatch_at(drafts, pos);
        if owner.is_none() && call.mode == "report" && matches(&REVIEWED, &scan.flat) {
            owner = Some(add_report_review(scan, line, context, pos, drafts));
        }
        if let Some(owner) = owner {
            let runs = &mut drafts[owner].external.runs;
            if runs.is_none() {
                *runs = Some(Runs::Skill {
                    skill: call.skill,
                    mode: call.mode,
                });
            }
            continue;
        }
        out.push(skill_item(scan, &call, line, context, pos));
    }
}

/// An independent `report` review dispatch; a second one in the same block
/// and line replaces the first.
fn add_report_review(
    scan: &BlockScan,
    line: &BlockLine,
    context: &str,
    pos: usize,
    drafts: &mut Vec<Draft>,
) -> usize {
    let mut external = new_external(ExternalType::Agent, "review".to_string(), context, line.n);
    external.table = scan.block.table;
    external.conditional = scan.classify(pos).1;
    external.report_order = true;
    let span = (-(line.n as i64), -(line.n as i64));
    let draft = Draft {
        span,
        external,
        edits: scan.edits(pos),
    };
    match drafts.iter().position(|d| d.span == span) {
        Some(index) => {
            drafts[index] = draft;
            index
        }
        None => {
            drafts.push(draft);
            drafts.len() - 1
        }
    }
}

fn skill_item(
    scan: &BlockScan,
    call: &SkillCall,
    line: &BlockLine,
    context: &str,
    pos: usize,
) -> Scanned {
    let (kind, conditional) = scan.classify(pos);
    let (_, stop) = bounds(&scan.flat, pos, &END);
    let tail = slice(&scan.flat, call.mode_end, stop);
    let mut external = new_external(
        ExternalType::Skill,
        format!("{} {}", call.skill, call.mode),
        context,
        line.n,
    );
    external.skill = call.skill.clone();
    external.mode = call.mode.clone();
    external.conditional = conditional;
    external.kind = kind;
    external.table = scan.block.table;
    external.qualifier = qualifier_of(tail);
    Scanned {
        section: scan.block.heading.clone(),
        edits: scan.edits(pos),
        body: Body::External(external),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn raws(line: &str, fenced: bool) -> Vec<String> {
        targets(line, fenced).into_iter().map(|t| t.raw).collect()
    }

    #[test]
    fn path_lookbehind_needs_a_boundary_before_the_directory() {
        assert_eq!(raws("`see references/a.md`", false), ["references/a.md"]);
        assert_eq!(raws("`../assets/b.png`", false), ["assets/b.png"]);
        assert_eq!(raws("`(scripts/c.sh)`", false), ["scripts/c.sh"]);
        assert!(raws("`xreferences/a.md`", false).is_empty());
    }

    #[test]
    fn script_lookbehind_needs_a_boundary_in_fenced_lines() {
        assert_eq!(raws("python3 scripts/run.py --x", true), ["scripts/run.py"]);
        assert_eq!(raws("./scripts/run.py", true), ["scripts/run.py"]);
        assert!(raws("myscripts/run.py", true).is_empty());
        assert!(raws("cat references/a.md", true).is_empty());
    }

    #[test]
    fn end_lookahead_needs_whitespace_after_the_stop() {
        let text = "Read v1.5 first. Then stop.";
        assert_eq!(sentence_at(text, 0, &END), "Read v1.5 first.");
        assert_eq!(sentence_at(text, 20, &END), " Then stop.");
    }

    #[test]
    fn clause_lookahead_ends_at_a_semicolon_before_whitespace() {
        let text = "Read a; then b; keep a;b. Done.";
        assert_eq!(sentence_at(text, 0, &CLAUSE), "Read a;");
        assert_eq!(sentence_at(text, 9, &CLAUSE), " then b;");
        assert_eq!(sentence_at(text, 17, &CLAUSE), " keep a;b.");
    }

    #[test]
    fn handoff_negative_lookahead_skips_instead_of() {
        assert!(!matches(&HANDOFF, "use this instead of that"));
        assert!(matches(&HANDOFF, "do this instead."));
        assert!(matches(&HANDOFF, "then continue with the plan"));
    }

    #[test]
    fn normpath_collapses_dots_like_posix() {
        assert_eq!(normpath("references/../scripts/./a.sh"), "scripts/a.sh");
        assert_eq!(normpath("../a.md"), "../a.md");
        assert_eq!(normpath("a//b"), "a/b");
        assert_eq!(normpath("."), ".");
    }

    fn write(root: &Path, rel: &str, text: &str) {
        let path = root.join(rel);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, text).unwrap();
    }

    #[test]
    fn resolve_tries_each_enclosing_folder_for_a_path_and_one_for_a_link() {
        let tmp = TempDir::new().unwrap();
        let skill = tmp.path().join("demo");
        write(&skill, "SKILL.md", "x");
        write(&skill, "references/a/b.md", "x");
        write(&skill, "references/top.md", "x");
        let dir = SkillDir::new(&skill);
        let found = |source: &str, raw: &str, link: bool| resolve(&dir, source, raw, link);
        assert_eq!(
            found("references/a/c.md", "references/top.md", false),
            (Some("references/top.md".to_string()), false)
        );
        assert_eq!(
            found("references/a/c.md", "b.md#intro", true),
            (Some("references/a/b.md".to_string()), false)
        );
        // A link resolves from the source's folder only; a miss is reported.
        assert_eq!(
            found("references/a/c.md", "top.md", true),
            (Some("references/a/top.md".to_string()), false)
        );
        assert_eq!(found("SKILL.md", "references/<x>.md", false), (None, true));
        assert_eq!(found("SKILL.md", "references/dir/", false), (None, true));
        assert_eq!(found("SKILL.md", "../out.md", true), (None, true));
    }

    #[test]
    fn blocks_group_lines_and_mark_case_and_role_headings() {
        let lines = [
            "# Title",
            "## If stale",
            "Read `references/a.md`.",
            "second line",
            "",
            "| a | b |",
            "## The reviewer",
            "- one",
            "```sh",
            "run scripts/x.sh",
            "```",
        ];
        let found = blocks(&lines);
        let summary: Vec<_> = found
            .iter()
            .map(|b| (b.lines.len(), b.case, b.role, b.table, b.fenced))
            .collect();
        assert_eq!(
            summary,
            [
                (2, true, false, false, false),
                (1, true, false, true, false),
                (1, false, true, false, false),
                (1, false, true, false, true),
            ]
        );
        assert_eq!(found[2].heading, "The reviewer");
    }

    fn scan_text(skill_md: &str, rel: &str, text: &str) -> Vec<Scanned> {
        let tmp = TempDir::new().unwrap();
        let skill = tmp.path().join("demo");
        write(&skill, "SKILL.md", skill_md);
        write(&skill, rel, text);
        for name in ["a", "b", "c"] {
            write(&skill, &format!("references/{name}.md"), "x");
        }
        scan(&SkillDir::new(&skill), rel, &HashSet::new())
    }

    fn pointer_kinds(scanned: &[Scanned]) -> Vec<(String, EdgeKind, bool)> {
        scanned
            .iter()
            .filter_map(|s| match &s.body {
                Body::Pointer(p) => Some((p.to.clone(), p.kind, p.conditional)),
                Body::External(_) => None,
            })
            .collect()
    }

    #[test]
    fn classifies_load_handoff_mention_and_role_pointers() {
        let text = "Read `references/a.md`.\n\n\
                    Then continue with `references/b.md`.\n\n\
                    The tool `references/c.md` exists.\n\n\
                    The reviewer reads `references/a.md`.\n\n\
                    Use `references/b.md` when stale.\n";
        let kinds = pointer_kinds(&scan_text("x", "references/x.md", text));
        let expected = [
            ("references/a.md", EdgeKind::Load, false),
            ("references/b.md", EdgeKind::Handoff, false),
            ("references/c.md", EdgeKind::Mention, false),
            ("references/a.md", EdgeKind::Role, false),
            ("references/b.md", EdgeKind::Load, true),
        ];
        let expected: Vec<_> = expected
            .iter()
            .map(|(p, k, c)| (p.to_string(), *k, *c))
            .collect();
        assert_eq!(kinds, expected);
    }

    #[test]
    fn a_table_row_outside_skill_md_is_a_conditional_load() {
        let text = "| Case | Read |\n|---|---|\n| One | `references/a.md` |\n";
        let kinds = pointer_kinds(&scan_text("x", "references/x.md", text));
        assert_eq!(
            kinds,
            [("references/a.md".to_string(), EdgeKind::Load, true)]
        );
    }

    fn externals(scanned: Vec<Scanned>) -> Vec<External> {
        scanned
            .into_iter()
            .filter_map(|s| match s.body {
                Body::External(x) => Some(x),
                Body::Pointer(_) => None,
            })
            .collect()
    }

    #[test]
    fn finds_inline_skill_modes_with_a_route_qualifier() {
        let text = "Run `varde-change` build via its builder route.\n";
        let found = externals(scan_text("x", "references/x.md", text));
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].target, "varde-change build");
        assert_eq!(found[0].kind, EdgeKind::Load);
        assert_eq!(found[0].qualifier.as_deref(), Some("builder"));
    }

    #[test]
    fn a_dispatch_takes_the_file_named_after_for() {
        let text = "Dispatch a builder for `references/a.md`.\n";
        let found = externals(scan_text("x", "references/x.md", text));
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].external, ExternalType::Agent);
        assert_eq!(found[0].target, "builder");
        assert_eq!(
            found[0].runs,
            Some(Runs::File {
                file: "references/a.md".to_string()
            })
        );
    }

    #[test]
    fn an_independent_report_span_is_a_review_dispatch() {
        let text = "Run an independent `varde-review report` on the diff.\n";
        let found = externals(scan_text("x", "references/x.md", text));
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].target, "review");
        assert!(found[0].report_order);
        assert_eq!(
            found[0].runs,
            Some(Runs::Skill {
                skill: "varde-review".to_string(),
                mode: "report".to_string()
            })
        );
    }

    #[test]
    fn short_trims_markup_and_ellipsizes() {
        assert_eq!(short("**Bold** `code`"), "Bold code");
        assert_eq!(short_to("abcdefghij", 8), "abcde...");
    }
}
