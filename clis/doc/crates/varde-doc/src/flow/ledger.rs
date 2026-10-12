//! Decision ledgers: port of the `ledger` half of `skill-flow.py`.
//!
//! A ledger lists a procedure's decisions (units = alternatives - 1, depth =
//! nesting) with cited source lines. Cyclomatic = 1 + sum(units); cognitive =
//! sum(units * (1 + depth)). `hash` rewrites the ledger with Python's
//! `json.dumps(data, indent=2) + "\n"` formatting: key order kept, every
//! non-ASCII character escaped as `\uXXXX`.

use crate::cli::{LedgerAction, LedgerArgs};
use clap::Parser;
use serde::de::{Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{Number, json};
use sha2::{Digest, Sha256};
use std::fmt::{self, Write as _};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};

/// JSON that remembers object key order, as Python dicts do.
#[derive(Debug, Clone, PartialEq)]
enum Json {
    Null,
    Bool(bool),
    Num(Number),
    Str(String),
    Arr(Vec<Json>),
    Obj(Vec<(String, Json)>),
}

impl<'de> Deserialize<'de> for Json {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct JsonVisitor;
        impl<'de> Visitor<'de> for JsonVisitor {
            type Value = Json;

            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                f.write_str("any JSON value")
            }
            fn visit_unit<E>(self) -> Result<Json, E> {
                Ok(Json::Null)
            }
            fn visit_bool<E>(self, v: bool) -> Result<Json, E> {
                Ok(Json::Bool(v))
            }
            fn visit_i64<E>(self, v: i64) -> Result<Json, E> {
                Ok(Json::Num(v.into()))
            }
            fn visit_u64<E>(self, v: u64) -> Result<Json, E> {
                Ok(Json::Num(v.into()))
            }
            fn visit_f64<E>(self, v: f64) -> Result<Json, E> {
                Ok(Number::from_f64(v).map_or(Json::Null, Json::Num))
            }
            fn visit_str<E>(self, v: &str) -> Result<Json, E> {
                Ok(Json::Str(v.to_string()))
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Json, A::Error> {
                let mut items = Vec::new();
                while let Some(item) = seq.next_element()? {
                    items.push(item);
                }
                Ok(Json::Arr(items))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Json, A::Error> {
                let mut entries: Vec<(String, Json)> = Vec::new();
                while let Some((key, value)) = map.next_entry::<String, Json>()? {
                    // Like a Python dict: a repeated key keeps its first slot.
                    match entries.iter_mut().find(|(k, _)| *k == key) {
                        Some(slot) => slot.1 = value,
                        None => entries.push((key, value)),
                    }
                }
                Ok(Json::Obj(entries))
            }
        }
        deserializer.deserialize_any(JsonVisitor)
    }
}

impl Json {
    fn get(&self, key: &str) -> Option<&Json> {
        match self {
            Json::Obj(entries) => entries.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    fn as_str(&self) -> Option<&str> {
        match self {
            Json::Str(s) => Some(s),
            _ => None,
        }
    }

    fn as_i64(&self) -> Option<i64> {
        match self {
            Json::Num(n) => n.as_i64(),
            _ => None,
        }
    }

    /// `json.dumps(self)`: `indent` of `Some(n)` nests by `n` spaces; `None`
    /// is the one-line form (`", "` and `": "` separators). `sort_keys`
    /// orders object keys.
    fn dumps(&self, indent: Option<usize>, sort_keys: bool) -> String {
        let mut out = String::new();
        self.write(&mut out, indent, sort_keys, 0);
        out
    }

    fn write(&self, out: &mut String, indent: Option<usize>, sort_keys: bool, level: usize) {
        match self {
            Json::Null => out.push_str("null"),
            Json::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            Json::Num(n) => out.push_str(&n.to_string()),
            Json::Str(s) => write_string(out, s),
            Json::Arr(items) if items.is_empty() => out.push_str("[]"),
            Json::Obj(entries) if entries.is_empty() => out.push_str("{}"),
            Json::Arr(items) => {
                let parts = items.iter().map(|item| (None, item));
                write_container(out, ('[', ']'), parts, indent, sort_keys, level);
            }
            Json::Obj(entries) => {
                let mut parts: Vec<_> = entries.iter().map(|(k, v)| (Some(k), v)).collect();
                if sort_keys {
                    parts.sort_by(|a, b| a.0.cmp(&b.0));
                }
                write_container(out, ('{', '}'), parts.into_iter(), indent, sort_keys, level);
            }
        }
    }
}

fn write_container<'a>(
    out: &mut String,
    (open, close): (char, char),
    parts: impl Iterator<Item = (Option<&'a String>, &'a Json)>,
    indent: Option<usize>,
    sort_keys: bool,
    level: usize,
) {
    out.push(open);
    for (i, (key, value)) in parts.enumerate() {
        match indent {
            Some(n) => {
                out.push_str(if i == 0 { "\n" } else { ",\n" });
                out.push_str(&" ".repeat(n * (level + 1)));
            }
            None if i > 0 => out.push_str(", "),
            None => {}
        }
        if let Some(key) = key {
            write_string(out, key);
            out.push_str(": ");
        }
        value.write(out, indent, sort_keys, level + 1);
    }
    if let Some(n) = indent {
        out.push('\n');
        out.push_str(&" ".repeat(n * level));
    }
    out.push(close);
}

/// A JSON string as Python writes it with `ensure_ascii`: anything outside
/// space..`~` is escaped, astral characters as surrogate pairs.
fn write_string(out: &mut String, text: &str) {
    out.push('"');
    for c in text.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            ' '..='~' => out.push(c),
            _ => {
                let mut units = [0u16; 2];
                for unit in c.encode_utf16(&mut units) {
                    let _ = write!(out, "\\u{unit:04x}");
                }
            }
        }
    }
    out.push('"');
}

/// Python's `str.splitlines()`.
fn splitlines(text: &str) -> Vec<String> {
    let mut lines = Vec::new();
    let mut current = String::new();
    let mut chars = text.chars().peekable();
    while let Some(c) = chars.next() {
        match c {
            '\r'
            | '\n'
            | '\u{b}'
            | '\u{c}'
            | '\u{1c}'..='\u{1e}'
            | '\u{85}'
            | '\u{2028}'
            | '\u{2029}' => {
                if c == '\r' && chars.peek() == Some(&'\n') {
                    chars.next();
                }
                lines.push(std::mem::take(&mut current));
            }
            _ => current.push(c),
        }
    }
    if !current.is_empty() {
        lines.push(current);
    }
    lines
}

fn lines_hash(lines: &[String]) -> String {
    format!("{:x}", Sha256::digest(lines.join("\n").as_bytes()))
}

/// The lines of `root/rel`, or `None` when it is not a readable UTF-8 file.
fn source_lines(root: &Path, rel: &str) -> Option<Vec<String>> {
    let file = root.join(rel);
    if !file.is_file() {
        return None;
    }
    String::from_utf8(fs::read(file).ok()?)
        .ok()
        .map(|text| splitlines(&text))
}

struct Decision {
    id: String,
    phase: String,
    source: String,
    line_start: i64,
    line_end: i64,
    alternatives: usize,
    units: Option<i64>,
    depth: Option<i64>,
    hash: Option<String>,
}

impl Decision {
    fn parse(value: &Json) -> Result<Self, String> {
        let text = |key: &str| {
            value
                .get(key)
                .and_then(Json::as_str)
                .map(str::to_string)
                .ok_or_else(|| format!("decision field {key:?} is missing or not a string"))
        };
        let number = |key: &str| {
            value
                .get(key)
                .and_then(Json::as_i64)
                .ok_or_else(|| format!("decision field {key:?} is missing or not an integer"))
        };
        let alternatives = match value.get("alternatives") {
            Some(Json::Arr(items)) => items.len(),
            _ => return Err("decision field \"alternatives\" is missing or not a list".into()),
        };
        Ok(Decision {
            id: text("id")?,
            phase: text("phase")?,
            source: text("source")?,
            line_start: number("line_start")?,
            line_end: number("line_end")?,
            alternatives,
            units: value.get("units").and_then(Json::as_i64),
            depth: value.get("depth").and_then(Json::as_i64),
            hash: value.get("hash").and_then(Json::as_str).map(str::to_string),
        })
    }

    /// The cited lines, or `None` when the file or range is missing.
    fn cited_lines(&self, root: &Path) -> Option<Vec<String>> {
        let lines = source_lines(root, &self.source)?;
        let (start, end) = (self.line_start, self.line_end);
        if !(1 <= start && start <= end && end <= lines.len() as i64) {
            return None;
        }
        Some(lines[start as usize - 1..end as usize].to_vec())
    }

    /// The 1-based range of the same lines elsewhere in the file.
    fn find_moved(&self, root: &Path) -> Option<(usize, usize)> {
        let lines = source_lines(root, &self.source).unwrap_or_default();
        let size = usize::try_from(self.line_end - self.line_start + 1).ok()?;
        (0..(lines.len() + 1).saturating_sub(size))
            .find(|&i| Some(lines_hash(&lines[i..i + size])) == self.hash)
            .map(|i| (i + 1, i + size))
    }
}

struct Ledger {
    decisions: Vec<Decision>,
    files: Vec<String>,
    routes: Vec<(String, Vec<String>)>,
}

impl Ledger {
    fn parse(data: &Json) -> Result<Self, String> {
        let list = |key: &str| match data.get(key) {
            Some(Json::Arr(items)) => Ok(items.as_slice()),
            _ => Err(format!("ledger field {key:?} is missing or not a list")),
        };
        let decisions = list("decisions")?
            .iter()
            .map(Decision::parse)
            .collect::<Result<_, _>>()?;
        let files = list("files")?
            .iter()
            .map(|file| {
                let path = file.get("path").and_then(Json::as_str);
                path.map(str::to_string)
                    .ok_or_else(|| "file entry has no string \"path\"".to_string())
            })
            .collect::<Result<_, _>>()?;
        let routes = match data.get("routes") {
            Some(Json::Obj(entries)) => entries
                .iter()
                .map(|(name, phases)| match phases {
                    Json::Arr(items) => Ok((
                        name.clone(),
                        items
                            .iter()
                            .filter_map(|p| p.as_str().map(str::to_string))
                            .collect(),
                    )),
                    _ => Err(format!("route {name:?} is not a list")),
                })
                .collect::<Result<_, _>>()?,
            _ => Vec::new(),
        };
        Ok(Ledger {
            decisions,
            files,
            routes,
        })
    }
}

struct Phase {
    name: String,
    decisions: i64,
    branch_units: i64,
    cognitive: i64,
}

struct Scores {
    decisions: usize,
    branch_units: i64,
    cognitive: i64,
    phases: Vec<Phase>,
}

impl Scores {
    fn cyclomatic(&self) -> i64 {
        1 + self.branch_units
    }

    fn to_json(&self) -> serde_json::Value {
        let phases: serde_json::Map<_, _> = self
            .phases
            .iter()
            .map(|p| {
                let row = json!({
                    "decisions": p.decisions,
                    "branch_units": p.branch_units,
                    "cognitive": p.cognitive,
                });
                (p.name.clone(), row)
            })
            .collect();
        json!({
            "decisions": self.decisions,
            "branch_units": self.branch_units,
            "cyclomatic": self.cyclomatic(),
            "cognitive": self.cognitive,
            "phases": phases,
        })
    }

    fn render_text(&self) -> String {
        let mut out = format!(
            "cyclomatic {} cognitive {} decisions {} branch_units {}\n",
            self.cyclomatic(),
            self.cognitive,
            self.decisions,
            self.branch_units
        );
        for p in &self.phases {
            let _ = writeln!(
                out,
                "  {}: {} decisions, {} units, cognitive {}",
                p.name, p.decisions, p.branch_units, p.cognitive
            );
        }
        out
    }
}

fn scores(ledger: &Ledger, route: Option<&str>) -> Result<Scores, String> {
    let phases = route.and_then(|name| ledger.routes.iter().find(|(r, _)| r == name));
    let mut by_phase: Vec<Phase> = Vec::new();
    let mut total = 0;
    for d in &ledger.decisions {
        if phases.is_some_and(|(_, wanted)| !wanted.contains(&d.phase)) {
            continue;
        }
        let (Some(units), Some(depth)) = (d.units, d.depth) else {
            return Err(format!("{}: units and depth must be integers", d.id));
        };
        total += 1;
        let at = by_phase.iter().position(|p| p.name == d.phase);
        let row = match at {
            Some(i) => &mut by_phase[i],
            None => {
                by_phase.push(Phase {
                    name: d.phase.clone(),
                    decisions: 0,
                    branch_units: 0,
                    cognitive: 0,
                });
                by_phase.last_mut().expect("just pushed")
            }
        };
        row.decisions += 1;
        row.branch_units += units;
        row.cognitive += units * (1 + depth);
    }
    Ok(Scores {
        decisions: total,
        branch_units: by_phase.iter().map(|p| p.branch_units).sum(),
        cognitive: by_phase.iter().map(|p| p.cognitive).sum(),
        phases: by_phase,
    })
}

fn problems(ledger: &Ledger, data: &Json, root: &Path) -> Vec<String> {
    let mut found = Vec::new();
    let mut seen: Vec<&str> = Vec::new();
    for d in &ledger.decisions {
        if seen.contains(&d.id.as_str()) {
            found.push(format!("{}: duplicate decision id", d.id));
        }
        seen.push(&d.id);
        if d.alternatives < 2 || d.units != Some(d.alternatives as i64 - 1) {
            found.push(format!("{}: units do not match alternatives - 1", d.id));
        }
        if d.depth.is_none_or(|depth| depth < 0) {
            found.push(format!("{}: invalid depth", d.id));
        }
        match d.cited_lines(root) {
            None => found.push(format!(
                "{}: {} lines {}-{} not found",
                d.id, d.source, d.line_start, d.line_end
            )),
            Some(lines) if d.hash.as_deref() != Some(&lines_hash(&lines)) => {
                found.push(format!("{}: hash does not match cited lines", d.id));
            }
            Some(_) => {}
        }
    }
    for path in &ledger.files {
        if !root.join(path).is_file() {
            found.push(format!("file missing: {path}"));
        }
    }
    let calls = match data.get("unresolved_calls") {
        Some(Json::Arr(items)) => items.as_slice(),
        _ => &[],
    };
    for call in calls {
        let kind = call.get("kind").and_then(Json::as_str);
        if kind != Some("external-boundary") {
            found.push(format!("unresolved local call: {}", call.dumps(None, true)));
        }
    }
    found
}

fn stale(ledger: &Ledger, root: &Path) -> Vec<String> {
    let mut found = Vec::new();
    for d in &ledger.decisions {
        let current = d.cited_lines(root);
        if current.is_some_and(|lines| d.hash.as_deref() == Some(&lines_hash(&lines))) {
            continue;
        }
        let where_ = match d.find_moved(root) {
            Some((start, end)) => format!("moved to {} lines {start}-{end}", d.source),
            None => "changed or vanished".to_string(),
        };
        found.push(format!("{}: {where_}", d.id));
    }
    found
}

/// Set every decision's `hash` to the hash of its cited lines, keeping key
/// order (a new `hash` key goes last, as in a Python dict).
fn rehash(data: &mut Json, ledger: &Ledger, root: &Path) -> Result<(), String> {
    let Json::Obj(entries) = data else {
        return Err("ledger is not an object".into());
    };
    let Some((_, Json::Arr(items))) = entries.iter_mut().find(|(k, _)| k == "decisions") else {
        return Err("ledger has no decisions list".into());
    };
    for (item, d) in items.iter_mut().zip(&ledger.decisions) {
        let lines = d
            .cited_lines(root)
            .ok_or_else(|| format!("{}: cited lines not found", d.id))?;
        let (Json::Obj(fields), hash) = (item, Json::Str(lines_hash(&lines))) else {
            unreachable!("Decision::parse accepted a non-object");
        };
        match fields.iter_mut().find(|(k, _)| k == "hash") {
            Some(slot) => slot.1 = hash,
            None => fields.push(("hash".to_string(), hash)),
        }
    }
    Ok(())
}

fn git_root() -> PathBuf {
    let top = Command::new("git")
        .args(["rev-parse", "--show-toplevel"])
        .output();
    match top {
        Ok(out) if out.status.success() => {
            PathBuf::from(String::from_utf8_lossy(&out.stdout).trim())
        }
        _ => PathBuf::from("."),
    }
}

/// What a ledger command printed and its exit code.
#[derive(Debug, Default)]
pub struct Output {
    pub code: u8,
    pub stdout: String,
    pub stderr: String,
}

impl Output {
    fn out(code: u8, text: impl fmt::Display) -> Self {
        Output {
            code,
            stdout: format!("{text}"),
            ..Output::default()
        }
    }

    fn with_newline(mut self) -> Self {
        self.stdout.push('\n');
        self
    }

    fn input_error(args: &LedgerArgs, message: &str) -> Self {
        let text = if args.json {
            varde_core::envelope::tool_error("doc_flow_ledger_input", message).to_string()
        } else {
            message.to_string()
        };
        Output {
            code: 2,
            stderr: text + "\n",
            ..Output::default()
        }
    }
}

/// `varde doc flow ledger <action> <ledger.json>`: runs it and prints.
pub fn run(args: &LedgerArgs) -> ExitCode {
    let output = execute(args);
    print!("{}", output.stdout);
    eprint!("{}", output.stderr);
    ExitCode::from(output.code)
}

/// Run `varde doc flow ledger` with `args` (what follows `ledger`), without
/// printing.
pub fn run_captured(args: &[&str]) -> Result<Output, clap::Error> {
    let argv = ["varde doc", "flow", "ledger"]
        .into_iter()
        .chain(args.iter().copied());
    let cli = crate::cli::Cli::try_parse_from(argv)?;
    match cli.command {
        crate::cli::TopCommand::Flow(flow) => match flow.command {
            Some(crate::cli::FlowCommand::Ledger(ledger)) => Ok(execute(&ledger)),
            None => unreachable!("argv names the ledger subcommand"),
        },
        _ => unreachable!("argv names the flow command"),
    }
}

fn execute(args: &LedgerArgs) -> Output {
    let prefix = "varde doc flow ledger";
    let loaded = fs::read_to_string(&args.ledger)
        .map_err(|e| format!("{prefix}: {}: {e}", args.ledger.display()))
        .and_then(|text| {
            let bad = |e: serde_json::Error| format!("{prefix}: {}: {e}", args.ledger.display());
            serde_json::from_str::<Json>(&text).map_err(bad)
        })
        .and_then(|data| {
            let ledger = Ledger::parse(&data).map_err(|e| format!("{prefix}: {e}"))?;
            Ok((data, ledger))
        });
    let (mut data, ledger) = match loaded {
        Ok(pair) => pair,
        Err(message) => return Output::input_error(args, &message),
    };
    let root = args.root.clone().unwrap_or_else(git_root);
    match args.action {
        LedgerAction::Score => run_score(args, &ledger),
        LedgerAction::Hash => run_hash(args, &mut data, &ledger, &root),
        LedgerAction::Validate => {
            let found = problems(&ledger, &data, &root);
            report(args, "problems", "doc_ledger_problems", found)
        }
        LedgerAction::Check => {
            let found = stale(&ledger, &root);
            report(args, "stale", "doc_ledger_stale", found)
        }
    }
}

fn run_score(args: &LedgerArgs, ledger: &Ledger) -> Output {
    let route = args.route.as_deref();
    if let Some(name) = route.filter(|name| ledger.routes.iter().all(|(r, _)| r != name)) {
        let message = format!("varde doc flow ledger: ledger has no route '{name}'");
        return Output::input_error(args, &message);
    }
    let scores = match scores(ledger, route) {
        Ok(scores) => scores,
        Err(message) => {
            return Output::input_error(args, &format!("varde doc flow ledger: {message}"));
        }
    };
    if args.json {
        let meta = json!({ "truncated": false });
        Output::out(0, varde_core::envelope::success(scores.to_json(), meta)).with_newline()
    } else {
        Output::out(0, scores.render_text())
    }
}

fn run_hash(args: &LedgerArgs, data: &mut Json, ledger: &Ledger, root: &Path) -> Output {
    let written = rehash(data, ledger, root).and_then(|()| {
        let text = data.dumps(Some(2), false) + "\n";
        fs::write(&args.ledger, text).map_err(|e| format!("{}: {e}", args.ledger.display()))
    });
    let meta = json!({ "truncated": false });
    match written {
        Ok(()) if args.json => {
            let data = json!({ "hashed": ledger.decisions.len() });
            Output::out(0, varde_core::envelope::success(data, meta)).with_newline()
        }
        Ok(()) => Output::default(),
        Err(message) if args.json => {
            let details = json!({});
            let code = "doc_ledger_hash";
            let envelope = varde_core::envelope::negative_result(code, &message, details, meta);
            Output::out(1, envelope).with_newline()
        }
        Err(message) => Output {
            code: 1,
            stderr: message + "\n",
            ..Output::default()
        },
    }
}

/// `validate` and `check`: one line per finding, exit 1 if any.
fn report(args: &LedgerArgs, key: &str, code: &str, found: Vec<String>) -> Output {
    let meta = json!({ "truncated": false });
    match (found.is_empty(), args.json) {
        (true, false) => Output::default(),
        (true, true) => {
            let envelope = varde_core::envelope::success(json!({ key: found }), meta);
            Output::out(0, envelope).with_newline()
        }
        (false, false) => Output::out(1, found.join("\n")).with_newline(),
        (false, true) => {
            let message = format!("{} {key}", found.len());
            let details = json!({ key: found });
            let envelope = varde_core::envelope::negative_result(code, &message, details, meta);
            Output::out(1, envelope).with_newline()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dumps_matches_python_with_non_ascii_text() {
        // python3: json.dumps({"b": ["é", "\U0001F600", "\x7f", "a\"\\\n"], "a": {}, "c": []}, indent=2)
        let data: Json = serde_json::from_str(
            "{\"b\": [\"é\", \"😀\", \"\u{7f}\", \"a\\\"\\\\\\n\"], \"a\": {}, \"c\": []}",
        )
        .unwrap();
        let expected = "{\n  \"b\": [\n    \"\\u00e9\",\n    \"\\ud83d\\ude00\",\n    \"\\u007f\",\n    \"a\\\"\\\\\\n\"\n  ],\n  \"a\": {},\n  \"c\": []\n}";
        assert_eq!(data.dumps(Some(2), false), expected);
    }

    #[test]
    fn one_line_dump_sorts_keys_with_python_separators() {
        let data: Json = serde_json::from_str("{\"z\": 1, \"a\": [true, null, \"x\"]}").unwrap();
        assert_eq!(
            data.dumps(None, true),
            "{\"a\": [true, null, \"x\"], \"z\": 1}"
        );
    }

    #[test]
    fn splitlines_follows_python() {
        assert_eq!(splitlines("a\r\nb\rc\u{2028}d\n"), ["a", "b", "c", "d"]);
        assert_eq!(splitlines("a\n\nb"), ["a", "", "b"]);
        assert!(splitlines("").is_empty());
    }
}
