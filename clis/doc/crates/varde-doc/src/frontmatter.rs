//! `varde doc frontmatter`: validate `SKILL.md` frontmatter against the
//! agentskills.io spec. Port of `validate-frontmatter.py`.
//!
//! Intended divergences from the Python script (PyYAML, YAML 1.1) come from
//! parsing with `serde_yaml` (YAML 1.2 core schema):
//!
//! - YAML 1.1 scalars are plain strings here: `yes`/`no`/`on`/`off`, `1_000`,
//!   sexagesimal numbers (`1:30`) and timestamps. `metadata: {owner: yes}`
//!   passes, and `name: yes` reports "got str" rather than "got bool".
//!   YAML 1.2 reads `0o17` as an int, which PyYAML keeps as a string.
//! - Every `!!` tag (`!!str`, `!!python/object`) is rejected; PyYAML's safe
//!   loader accepts the standard ones. The check is a raw scan for `!!` where
//!   YAML allows a tag (value start, after `- `, `? `, flow `[`/`{`/`,` or an
//!   anchor). Block-scalar bodies and same-line quoted scalars are skipped;
//!   a `!!` inside a multi-line quoted scalar at such a position is rejected.
//! - YAML parse error wording differs. Duplicate keys (explicit, anchored or
//!   under merge keys) are still rejected, reported as `duplicate key`.
//! - A tab after a mapping `:` is accepted (PyYAML rejects it), and `1:` and
//!   `"1":` are one key here, so they give one unknown-key warning where
//!   PyYAML reports two.
//! - A quoted `"<<"` key is an ordinary key, as in PyYAML. The check is a raw
//!   scan: if a plain `<<` key appears anywhere, `<<` keys are merges.
//! - `repr()` of a bad `name` approximates Python's: control characters are
//!   escaped, other characters print as-is.
//!
//! Beyond the spec, `requires`/`recommends` name sibling skills: each must exist,
//! never `varde-manage`, and `requires` must resolve without an unknown name or
//! a cycle.

use serde_json::{Value as Json, json};
use serde_yaml::{Mapping, Value};
use std::collections::{BTreeMap, HashMap};
use std::fs;
use std::path::{Component, Path, PathBuf};
use varde_core::skill_relations::{self, RelationError};

const KNOWN_FIELDS: [&str; 8] = [
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
    "requires",
    "recommends",
];
const BODY_LINE_BUDGET: usize = 500;

/// The outcome of validating one `SKILL.md`.
#[derive(Debug, PartialEq, Eq)]
pub struct SkillResult {
    pub path: String,
    pub errors: Vec<String>,
    pub warnings: Vec<String>,
}

impl SkillResult {
    pub fn ok(&self) -> bool {
        self.errors.is_empty()
    }

    pub fn to_json(&self) -> Json {
        json!({
            "path": self.path,
            "errors": self.errors,
            "warnings": self.warnings,
            "ok": self.ok(),
        })
    }
}

/// Text output of the Python script: a status line per skill, then its messages.
pub fn render_text(results: &[SkillResult]) -> String {
    let mut out = String::new();
    for result in results {
        let status = if result.ok() { "OK  " } else { "FAIL" };
        out.push_str(&format!("{status}  {}\n", result.path));
        for error in &result.errors {
            out.push_str(&format!("      error:   {error}\n"));
        }
        for warning in &result.warnings {
            out.push_str(&format!("      warning: {warning}\n"));
        }
    }
    out
}

/// Bad input: a missing path, no `SKILL.md` found, or an unreadable file.
#[derive(Debug, PartialEq, Eq)]
pub struct InputError(pub String);

/// Validate every skill found under `paths`: a skill directory, a `SKILL.md`,
/// or a directory of skill directories (one level deep).
pub fn check(paths: &[PathBuf]) -> Result<Vec<SkillResult>, InputError> {
    let mut files = Vec::new();
    for raw in paths {
        let path = expand_tilde(raw);
        let shown = normalize(&path);
        if !path.exists() {
            return Err(InputError(format!(
                "varde doc frontmatter: path not found: {}",
                shown.display()
            )));
        }
        let found = find_skill_files(&path, &shown);
        if found.is_empty() {
            return Err(InputError(format!(
                "varde doc frontmatter: no SKILL.md found at or under {}",
                if shown.as_os_str().is_empty() {
                    Path::new(".").display()
                } else {
                    shown.display()
                }
            )));
        }
        files.extend(found);
    }
    let mut known_dirs: HashMap<PathBuf, BTreeMap<String, Vec<String>>> = HashMap::new();
    files
        .iter()
        .map(|(real, shown)| {
            let known = skills_root(real).map(|root| {
                &*known_dirs
                    .entry(root)
                    .or_insert_with_key(|root| load_requirements(root))
            });
            validate_skill(real, shown, known)
        })
        .collect()
}

/// The skills directory holding `skill_md`: the parent of its skill directory.
fn skills_root(skill_md: &Path) -> Option<PathBuf> {
    let root = skill_md.parent()?.parent()?;
    if root.as_os_str().is_empty() {
        return None;
    }
    Some(root.to_path_buf())
}

/// The `requires` list of every sibling skill under `root`, by directory name.
/// A skill whose frontmatter does not parse contributes an empty list; its own
/// validation reports the parse error.
fn load_requirements(root: &Path) -> BTreeMap<String, Vec<String>> {
    let mut requires = BTreeMap::new();
    let Ok(entries) = fs::read_dir(root) else {
        return requires;
    };
    for entry in entries.flatten() {
        let skill_md = entry.path().join("SKILL.md");
        let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
            continue;
        };
        if !skill_md.is_file() {
            continue;
        }
        let list = fs::read_to_string(&skill_md)
            .ok()
            .and_then(|text| frontmatter_relations(&text))
            .map(|relations| relations.requires)
            .unwrap_or_default();
        requires.insert(name, list);
    }
    requires
}

/// The declared relations in a `SKILL.md`, or `None` without frontmatter.
fn frontmatter_relations(text: &str) -> Option<skill_relations::Relations> {
    let text = text.replace("\r\n", "\n").replace('\r', "\n");
    let (raw, _) = split_frontmatter(&text)?;
    skill_relations::parse(raw).ok()
}

fn expand_tilde(path: &Path) -> PathBuf {
    let Ok(rest) = path.strip_prefix("~") else {
        return path.to_path_buf();
    };
    match std::env::var_os("HOME") {
        Some(home) => PathBuf::from(home).join(rest),
        None => path.to_path_buf(),
    }
}

/// Python `Path` display form: no `.` components or trailing slash.
fn normalize(path: &Path) -> PathBuf {
    path.components()
        .filter(|component| *component != Component::CurDir)
        .collect()
}

/// `(real path, display path)` pairs for the `SKILL.md` files at `path`.
fn find_skill_files(path: &Path, shown: &Path) -> Vec<(PathBuf, PathBuf)> {
    if path.is_file() && path.file_name().is_some_and(|name| name == "SKILL.md") {
        return vec![(path.to_path_buf(), shown.to_path_buf())];
    }
    if !path.is_dir() {
        return Vec::new();
    }
    let direct = path.join("SKILL.md");
    if direct.is_file() {
        return vec![(direct, shown.join("SKILL.md"))];
    }
    let mut children: Vec<_> = fs::read_dir(path)
        .map(|entries| {
            entries
                .filter_map(Result::ok)
                .map(|e| e.file_name())
                .collect()
        })
        .unwrap_or_default();
    children.sort();
    children
        .into_iter()
        .filter(|child| path.join(child).join("SKILL.md").is_file())
        .map(|child| {
            (
                path.join(&child).join("SKILL.md"),
                shown.join(&child).join("SKILL.md"),
            )
        })
        .collect()
}

fn dir_name(skill_md: &Path) -> String {
    match skill_md
        .parent()
        .and_then(|dir| dir.components().next_back())
    {
        Some(Component::Normal(name)) => name.to_string_lossy().into_owned(),
        Some(Component::ParentDir) => "..".to_string(),
        _ => String::new(),
    }
}

/// Validate one `SKILL.md`, reporting it as `shown`.
fn validate_skill(
    real: &Path,
    shown: &Path,
    known: Option<&BTreeMap<String, Vec<String>>>,
) -> Result<SkillResult, InputError> {
    let text = fs::read_to_string(real).map_err(|error| {
        InputError(format!(
            "varde doc frontmatter: {}: {error}",
            shown.display()
        ))
    })?;
    // Python reads with universal newlines.
    let text = text.replace("\r\n", "\n").replace('\r', "\n");
    let mut result = SkillResult {
        path: shown.to_string_lossy().into_owned(),
        errors: Vec::new(),
        warnings: Vec::new(),
    };
    let Some((raw, body_start)) = split_frontmatter(&text) else {
        result.errors.push(
            "no `---`-delimited YAML frontmatter block found at the top of the file".to_string(),
        );
        return Ok(result);
    };
    let frontmatter = match parse_mapping(raw) {
        Ok(frontmatter) => frontmatter,
        Err(message) => {
            result.errors.push(message);
            return Ok(result);
        }
    };
    let dir = dir_name(shown);
    check_fields(&frontmatter, raw, &dir, &mut result);
    check_relations(raw, &dir, known, &mut result.errors);
    let body_lines = text[body_start..].matches('\n').count() + 1;
    if body_lines > BODY_LINE_BUDGET {
        result.warnings.push(format!(
            "SKILL.md body is ~{body_lines} lines, over the {BODY_LINE_BUDGET}-line soft budget \
             \u{2014} consider moving detail into references/, assets/, or scripts/"
        ));
    }
    Ok(result)
}

/// The text between the opening and closing `---` lines, and where the body
/// starts. Mirrors the regex `^---\n(.*?)\n---\n?` (any text may follow the
/// closing `---` on its line, as in the Python script).
fn split_frontmatter(text: &str) -> Option<(&str, usize)> {
    let rest = text.strip_prefix("---\n")?;
    let close = rest.find("\n---")?;
    let mut end = 4 + close + 4;
    if text[end..].starts_with('\n') {
        end += 1;
    }
    Some((&rest[..close], end))
}

/// Frontmatter with merge keys applied, and whether it spelled out a
/// `description` key (inherited ones are not subject to the line check).
struct Frontmatter {
    fields: Mapping,
    explicit_description: bool,
}

fn parse_mapping(raw: &str) -> Result<Frontmatter, String> {
    let invalid = |detail: String| format!("frontmatter is not valid YAML: {detail}");
    let value: Value = serde_yaml::from_str(raw).map_err(|error| {
        invalid(
            error
                .to_string()
                .replace("duplicate entry with null key", "duplicate key")
                .replace("duplicate entry with key", "duplicate key")
                .replace("duplicate entry in YAML map", "duplicate key"),
        )
    })?;
    if let Some(problem) = unsupported(&value) {
        return Err(invalid(problem));
    }
    if let Some(tag) = find_secondary_tag(raw) {
        return Err(invalid(format!("unsupported tag `{tag}`")));
    }
    let Value::Mapping(top) = &value else {
        return Err("frontmatter must be a YAML mapping (key: value pairs)".to_string());
    };
    let explicit_description = top.contains_key("description");
    let value = if has_plain_merge_key(raw) {
        resolve_merges(value).map_err(invalid)?
    } else {
        value
    };
    match value {
        Value::Mapping(fields) => Ok(Frontmatter {
            fields,
            explicit_description,
        }),
        _ => Err("frontmatter must be a YAML mapping (key: value pairs)".to_string()),
    }
}

/// Apply `<<` merge keys bottom-up, so a merged-in mapping has its own merges
/// resolved. Explicit keys win, and earlier mappings in a list win.
fn resolve_merges(value: Value) -> Result<Value, String> {
    match value {
        Value::Sequence(items) => items
            .into_iter()
            .map(resolve_merges)
            .collect::<Result<_, _>>()
            .map(Value::Sequence),
        Value::Mapping(map) => {
            let mut resolved = Mapping::new();
            for (key, item) in map {
                resolved.insert(key, resolve_merges(item)?);
            }
            let Some(merge) = resolved.remove("<<") else {
                return Ok(Value::Mapping(resolved));
            };
            let sources = match merge {
                Value::Mapping(source) => vec![source],
                Value::Sequence(items) => items
                    .into_iter()
                    .map(|item| match item {
                        Value::Mapping(source) => Ok(source),
                        _ => Err(MERGE_ERROR.to_string()),
                    })
                    .collect::<Result<_, _>>()?,
                _ => return Err(MERGE_ERROR.to_string()),
            };
            for (key, item) in sources.into_iter().flatten() {
                resolved.entry(key).or_insert(item);
            }
            Ok(Value::Mapping(resolved))
        }
        other => Ok(other),
    }
}

/// Whether `<<` appears as a plain (unquoted) key; a quoted `"<<"` is an
/// ordinary key. `serde_yaml` does not keep the quoting, so this scans the text.
fn has_plain_merge_key(raw: &str) -> bool {
    raw.match_indices("<<").any(|(at, _)| {
        let before = raw[..at].chars().next_back();
        let after = raw[at + 2..].trim_start_matches([' ', '\t']);
        before.is_none_or(|c| c.is_whitespace() || "{,".contains(c))
            && after
                .strip_prefix(':')
                .is_some_and(|rest| rest.is_empty() || rest.starts_with([' ', '\t', '\n', '\r']))
    })
}

const MERGE_ERROR: &str = "expected a mapping or list of mappings for merging";

/// The first `!!` tag where YAML allows one. `serde_yaml` drops these when it
/// builds a `Value`, so they are found in the raw text, line by line.
fn find_secondary_tag(raw: &str) -> Option<String> {
    let mut block_indent: Option<usize> = None;
    let mut flow_depth = 0;
    for line in raw.lines() {
        let indent = line.len() - line.trim_start_matches(' ').len();
        if let Some(parent) = block_indent {
            if line.trim().is_empty() || indent > parent {
                continue;
            }
            block_indent = None;
        }
        match scan_line(line, &mut flow_depth) {
            LineScan::Tag(tag) => return Some(tag),
            LineScan::BlockScalar => block_indent = Some(indent),
            LineScan::Plain => {}
        }
    }
    None
}

enum LineScan {
    Tag(String),
    BlockScalar,
    Plain,
}

/// Scan one line, tracking whether the next token starts a value (where a tag
/// is allowed): at line start, after `- `, `? `, `: `, an anchor, or, inside
/// a flow collection, `[`, `{` and `,`.
fn scan_line(line: &str, flow_depth: &mut usize) -> LineScan {
    let chars: Vec<char> = line.chars().collect();
    let next_is_blank = |at: usize| chars.get(at + 1).is_none_or(|c| c.is_whitespace());
    let mut at = 0;
    let mut value_start = true;
    while at < chars.len() {
        let c = chars[at];
        if c.is_whitespace() {
            at += 1;
            continue;
        }
        let was_start = value_start;
        value_start = false;
        match c {
            '#' if at == 0 || chars[at - 1].is_whitespace() => break,
            '-' | '?' | ':' if next_is_blank(at) => value_start = true,
            '[' | '{' if was_start || *flow_depth > 0 => {
                *flow_depth += 1;
                value_start = true;
            }
            ']' | '}' if *flow_depth > 0 => *flow_depth -= 1,
            ',' if *flow_depth > 0 => value_start = true,
            '&' if was_start => {
                while at < chars.len() && !chars[at].is_whitespace() {
                    at += 1;
                }
                value_start = true;
                continue;
            }
            '|' | '>' if was_start && is_block_header(&chars[at + 1..]) => {
                return LineScan::BlockScalar;
            }
            '"' | '\'' if was_start => {
                if let Some(close) = closing_quote(&chars, at) {
                    at = close;
                }
            }
            '!' if was_start && chars.get(at + 1) == Some(&'!') => {
                let tag = chars[at..]
                    .iter()
                    .take_while(|c| !c.is_whitespace() && !",]}".contains(**c))
                    .collect();
                return LineScan::Tag(tag);
            }
            _ => {}
        }
        at += 1;
    }
    LineScan::Plain
}

/// The rest of a block scalar header after `|` or `>`: indentation and
/// chomping indicators, then an optional comment.
fn is_block_header(rest: &[char]) -> bool {
    let tail: String = rest
        .iter()
        .skip_while(|c| c.is_ascii_digit() || "+-".contains(**c))
        .collect();
    let tail = tail.trim();
    tail.is_empty() || tail.starts_with('#')
}

/// Index of the quote closing the scalar opened at `open`, if it closes on
/// this line: `''` escapes in single quotes, backslash in double quotes.
fn closing_quote(chars: &[char], open: usize) -> Option<usize> {
    let quote = chars[open];
    let mut at = open + 1;
    while at < chars.len() {
        match chars[at] {
            '\\' if quote == '"' => at += 1,
            c if c == quote => {
                if quote == '\'' && chars.get(at + 1) == Some(&'\'') {
                    at += 1;
                } else {
                    return Some(at);
                }
            }
            _ => {}
        }
        at += 1;
    }
    None
}

/// PyYAML's safe loader cannot build tagged values or collection keys.
fn unsupported(value: &Value) -> Option<String> {
    match value {
        Value::Tagged(tagged) => Some(format!("unsupported tag `{}`", tagged.tag)),
        Value::Sequence(items) => items.iter().find_map(unsupported),
        Value::Mapping(map) => map.iter().find_map(|(key, item)| {
            if matches!(key, Value::Sequence(_) | Value::Mapping(_)) {
                return Some("found unhashable key".to_string());
            }
            unsupported(key).or_else(|| unsupported(item))
        }),
        _ => None,
    }
}

fn check_fields(frontmatter: &Frontmatter, raw: &str, dir: &str, result: &mut SkillResult) {
    let fields = &frontmatter.fields;
    let errors = &mut result.errors;

    match fields.get("name") {
        Some(name) if !is_falsy(name) => match name {
            Value::String(name) => check_name(name, dir, errors),
            other => errors.push(format!("`name` must be a string, got {}", type_name(other))),
        },
        _ => errors.push("missing required field `name`".to_string()),
    }

    match fields.get("description") {
        Some(description) if !is_falsy(description) => match description {
            Value::String(text) if text.trim().is_empty() => {
                errors.push("missing required field `description`".to_string());
            }
            Value::String(text) => {
                let length = text.chars().count();
                if length > 1024 {
                    errors.push(format!("`description` is {length} chars, max is 1024"));
                }
            }
            other => errors.push(format!(
                "`description` must be a string, got {}",
                type_name(other)
            )),
        },
        _ => errors.push("missing required field `description`".to_string()),
    }
    if frontmatter.explicit_description && !description_is_one_quoted_line(raw) {
        errors.push("`description` must be one double-quoted physical line".to_string());
    }

    match fields.get("compatibility") {
        None | Some(Value::Null) => {}
        Some(Value::String(text)) => {
            let length = text.chars().count();
            if length > 500 {
                errors.push(format!("`compatibility` is {length} chars, max is 500"));
            }
        }
        Some(other) => errors.push(format!(
            "`compatibility` must be a string, got {}",
            type_name(other)
        )),
    }

    match fields.get("metadata") {
        None | Some(Value::Null) => {}
        Some(Value::Mapping(map))
            if map
                .iter()
                .all(|(key, value)| key.is_string() && value.is_string()) => {}
        Some(_) => {
            errors.push("`metadata` must be a map of string keys to string values".to_string());
        }
    }

    match fields.get("allowed-tools") {
        None | Some(Value::Null | Value::String(_)) => {}
        Some(other) => errors.push(format!(
            "`allowed-tools` must be a string, got {}",
            type_name(other)
        )),
    }

    let mut unknown: Vec<String> = fields
        .keys()
        .filter(|key| !key.as_str().is_some_and(|key| KNOWN_FIELDS.contains(&key)))
        .map(display_key)
        .collect();
    unknown.sort();
    unknown.dedup();
    for key in unknown {
        result.warnings.push(format!(
            "unrecognized frontmatter field `{key}` (client-specific fields are fine)"
        ));
    }
}

/// Lint `requires`/`recommends`: each names an existing sibling skill, never
/// `varde-manage`, and `requires` resolves without an unknown name or a cycle.
fn check_relations(
    raw: &str,
    dir: &str,
    known: Option<&BTreeMap<String, Vec<String>>>,
    errors: &mut Vec<String>,
) {
    let relations = match skill_relations::parse(raw) {
        Ok(relations) => relations,
        Err(error) => {
            errors.push(error.to_string());
            return;
        }
    };
    for name in relations.requires.iter().chain(relations.recommends.iter()) {
        if name == skill_relations::IMPLICIT_SKILL {
            errors.push(format!(
                "must not list `{}`; it is installed implicitly",
                skill_relations::IMPLICIT_SKILL
            ));
        }
    }
    let Some(known) = known else {
        return;
    };
    for name in &relations.recommends {
        if name == dir {
            errors.push("`recommends` must not name the skill itself".to_string());
        } else if !known.contains_key(name) {
            errors.push(format!("`recommends` names unknown skill `{name}`"));
        }
    }
    if relations.requires.is_empty() {
        return;
    }
    let selected = vec![dir.to_string()];
    match skill_relations::closure(&selected, |name| known.get(name).cloned()) {
        Ok(_) => {}
        Err(RelationError::Unknown(name)) => {
            errors.push(format!("`requires` names unknown skill `{name}`"));
        }
        Err(error) => errors.push(error.to_string()),
    }
}

fn check_name(name: &str, dir: &str, errors: &mut Vec<String>) {
    let length = name.chars().count();
    if length > 64 {
        errors.push(format!("`name` is {length} chars, max is 64"));
    }
    if !is_valid_name(name) {
        errors.push(format!(
            "`name` {} must be lowercase alphanumeric + hyphens only, \
             no leading/trailing hyphen, no consecutive hyphens",
            py_repr(name)
        ));
    }
    if name != dir {
        errors.push(format!(
            "`name` {} must match parent directory name {}",
            py_repr(name),
            py_repr(dir)
        ));
    }
}

/// `^[a-z0-9]+(-[a-z0-9]+)*$`
fn is_valid_name(name: &str) -> bool {
    name.split('-').all(|part| {
        !part.is_empty()
            && part
                .bytes()
                .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit())
    })
}

/// The `description:` key sits at column 0 and its value is a double-quoted
/// scalar that opens and closes on that same line.
fn description_is_one_quoted_line(raw: &str) -> bool {
    let Some(line) = raw
        .split('\n')
        .find(|line| line.starts_with("description:"))
    else {
        return false;
    };
    let Some(value) = line["description:".len()..].trim_start().strip_prefix('"') else {
        return false;
    };
    let mut chars = value.chars();
    while let Some(c) = chars.next() {
        match c {
            '\\' => {
                chars.next();
            }
            '"' => return true,
            _ => {}
        }
    }
    false
}

/// Python truthiness: `not value`.
fn is_falsy(value: &Value) -> bool {
    match value {
        Value::Null => true,
        Value::Bool(flag) => !flag,
        Value::Number(number) => number.as_f64() == Some(0.0),
        Value::String(text) => text.is_empty(),
        Value::Sequence(items) => items.is_empty(),
        Value::Mapping(map) => map.is_empty(),
        Value::Tagged(_) => false,
    }
}

/// Python's `type(value).__name__`.
fn type_name(value: &Value) -> &'static str {
    match value {
        Value::Null => "NoneType",
        Value::Bool(_) => "bool",
        Value::Number(number) if number.is_f64() => "float",
        Value::Number(_) => "int",
        Value::String(_) => "str",
        Value::Sequence(_) => "list",
        Value::Mapping(_) => "dict",
        Value::Tagged(_) => "tagged",
    }
}

/// Python's `str(key)` for a scalar mapping key.
fn display_key(key: &Value) -> String {
    match key {
        Value::Null => "None".to_string(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
        Value::Number(number) => number.to_string(),
        Value::String(text) => text.clone(),
        _ => String::new(),
    }
}

/// Python's `repr()` of a string.
fn py_repr(text: &str) -> String {
    let quote = if text.contains('\'') && !text.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::from(quote);
    for c in text.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if c.is_control() && (c as u32) < 0x100 => {
                out.push_str(&format!("\\x{:02x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}
