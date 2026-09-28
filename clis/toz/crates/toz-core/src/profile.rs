//! Per-command output profiles: `[[profile]]` TOML entries loaded from three scopes
//! (built-in, user, project) and merged by `id`, later scope wins.
//!
//! This module owns loading, validation, and matching a profile against a capture
//! (`find_match`). Running a matched profile's script is a separate concern (later plans).

use crate::project::Project;
use regex::Regex;
use serde::Serialize;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// Embedded built-in profiles (`builtin_profiles.toml`). Downstream plans add further entries.
const BUILTIN_PROFILES_TOML: &str = include_str!("builtin_profiles.toml");

/// Where a loaded profile came from. Later scopes override earlier ones with the same `id`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Scope {
    Builtin,
    User,
    Project,
}

impl Scope {
    fn as_str(self) -> &'static str {
        match self {
            Scope::Builtin => "builtin",
            Scope::User => "user",
            Scope::Project => "project",
        }
    }
}

impl std::fmt::Display for Scope {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Which hook value a profile's `match` table is compared against.
#[derive(Debug, Clone)]
pub enum MatchSpec {
    /// Matched against the hook command line.
    Command(GlobPattern),
    /// Matched against `--source`.
    Source(GlobPattern),
}

/// A glob pattern (`*`, `?`, `[...]`) plus its compiled matcher.
#[derive(Debug, Clone)]
pub struct GlobPattern {
    pub pattern: String,
    regex: Regex,
}

impl GlobPattern {
    pub(crate) fn compile(pattern: &str) -> Result<Self, String> {
        let regex = glob_to_regex(pattern)?;
        Ok(Self {
            pattern: pattern.to_string(),
            regex,
        })
    }

    pub fn is_match(&self, value: &str) -> bool {
        self.regex.is_match(value)
    }
}

/// How a capture's text is split into sections.
#[derive(Debug, Clone)]
pub enum SectionsSpec {
    /// Each line matching the regex starts a new section; capture group 1 (if present) titles it.
    Heading(Regex),
    /// Same as `Heading`, matched with `find` semantics rather than a titled heading.
    Start(Regex),
    /// JSON-Lines input: group by the value of this top-level key.
    JsonlKey(String),
}

#[derive(Debug, Clone, Copy)]
pub enum PreviewKind {
    Toc,
    Head,
}

#[derive(Debug, Clone)]
pub struct PreviewSpec {
    pub kind: PreviewKind,
    pub items_per_section: Option<usize>,
    pub item: Option<Regex>,
}

#[derive(Debug, Clone)]
pub struct ProfileTest {
    pub name: String,
    pub input: String,
    pub expect_records: Option<toml::Value>,
    pub expect_preview_contains: Vec<String>,
}

/// One loaded, validated `[[profile]]` entry.
#[derive(Debug, Clone)]
pub struct Profile {
    pub id: String,
    pub scope: Scope,
    pub file: PathBuf,
    pub match_spec: Option<MatchSpec>,
    pub sections: Option<SectionsSpec>,
    /// Default `true`, matching today's chunking behavior.
    pub merge_small: bool,
    pub preview: Option<PreviewSpec>,
    /// `None` when the entry had no script, or when a project-scope script was dropped for trust.
    pub script: Option<String>,
    pub tests: Vec<ProfileTest>,
}

impl Profile {
    pub fn has_script(&self) -> bool {
        self.script.is_some()
    }
}

/// The first profile whose `match` fires for this capture: project scope beats user beats
/// builtin, and ties within a scope keep loader order. `match.command` only fires when
/// `is_command` is set (the origin is a literal command line, e.g. a `run` or `hook:<tool>`
/// capture); `match.source` fires for any capture's origin string.
pub fn find_match<'a>(
    profiles: &'a [Profile],
    source: &str,
    is_command: bool,
) -> Option<&'a Profile> {
    let mut ordered: Vec<&Profile> = profiles.iter().collect();
    ordered.sort_by_key(|p| match p.scope {
        Scope::Project => 0,
        Scope::User => 1,
        Scope::Builtin => 2,
    });
    ordered.into_iter().find(|p| match &p.match_spec {
        Some(MatchSpec::Source(g)) => g.is_match(source),
        Some(MatchSpec::Command(g)) => is_command && g.is_match(source),
        None => false,
    })
}

/// A skipped or downgraded profile entry, or a file-level parse failure.
#[derive(Debug, Clone, Serialize)]
pub struct Diagnostic {
    pub profile_id: Option<String>,
    pub file: PathBuf,
    pub reason: String,
}

impl Diagnostic {
    fn new(profile_id: Option<String>, file: &Path, reason: impl Into<String>) -> Self {
        Self {
            profile_id,
            file: file.to_path_buf(),
            reason: reason.into(),
        }
    }
}

/// JSON-friendly summary of a loaded profile, for `toz profile list`.
#[derive(Debug, Serialize)]
pub struct ProfileSummary {
    pub id: String,
    pub scope: Scope,
    pub file: String,
    pub has_script: bool,
}

impl From<&Profile> for ProfileSummary {
    fn from(p: &Profile) -> Self {
        Self {
            id: p.id.clone(),
            scope: p.scope,
            file: p.file.display().to_string(),
            has_script: p.has_script(),
        }
    }
}

pub fn summarize(profiles: &[Profile]) -> Vec<ProfileSummary> {
    profiles.iter().map(ProfileSummary::from).collect()
}

/// Root directory for varde-wide config: `$VARDE_CONFIG_DIR`, else `$XDG_CONFIG_HOME/varde`,
/// else `~/.config/varde`. Mirrors `md-core`'s user-config lookup; this crate cannot depend on
/// `md-core` (separate Cargo workspace), so the same rule is reimplemented here.
pub(crate) fn varde_config_dir() -> PathBuf {
    if let Some(dir) = std::env::var_os("VARDE_CONFIG_DIR").filter(|v| !v.is_empty()) {
        return PathBuf::from(dir);
    }
    if let Some(dir) = std::env::var_os("XDG_CONFIG_HOME").filter(|v| !v.is_empty()) {
        return PathBuf::from(dir).join("varde");
    }
    dirs::home_dir()
        .map(|home| home.join(".config"))
        .unwrap_or_else(|| PathBuf::from(".config"))
        .join("varde")
}

/// User-scope profiles file: `<varde config dir>/toz/profiles.toml`.
pub fn user_profiles_path() -> PathBuf {
    varde_config_dir().join("toz").join("profiles.toml")
}

/// Project-scope profiles file: `<project root>/.varde/toz-profiles.toml`.
pub fn project_profiles_path(project: &Project) -> PathBuf {
    project.root.join(".varde").join("toz-profiles.toml")
}

/// Load and merge profiles for `project` from all three scopes. Loading never fails: a missing
/// file is treated as empty, and a malformed entry becomes a diagnostic instead of an error.
pub fn load_profiles(project: &Project) -> (Vec<Profile>, Vec<Diagnostic>) {
    load_from_paths(
        &user_profiles_path(),
        &project_profiles_path(project),
        &project.root,
    )
}

/// Load only the profiles in `path`, treated as user scope so any `script` runs unconditionally
/// (matches `toz profile test --file <path>`, which is not subject to project trust). A missing
/// file is a diagnostic rather than a fatal error; a malformed entry is likewise a diagnostic.
pub fn load_file(path: &Path) -> (Vec<Profile>, Vec<Diagnostic>) {
    let mut diagnostics = Vec::new();
    let mut by_id: BTreeMap<String, Profile> = BTreeMap::new();
    match std::fs::read_to_string(path) {
        Ok(text) => load_scope(&text, Scope::User, path, None, &mut by_id, &mut diagnostics),
        Err(e) => diagnostics.push(Diagnostic::new(
            None,
            path,
            format!("cannot read file: {e}"),
        )),
    }
    (by_id.into_values().collect(), diagnostics)
}

fn load_from_paths(
    user_path: &Path,
    project_path: &Path,
    project_root: &Path,
) -> (Vec<Profile>, Vec<Diagnostic>) {
    let mut diagnostics = Vec::new();
    let mut by_id: BTreeMap<String, Profile> = BTreeMap::new();

    load_scope(
        BUILTIN_PROFILES_TOML,
        Scope::Builtin,
        Path::new("<builtin>"),
        None,
        &mut by_id,
        &mut diagnostics,
    );

    let mut trusted_projects: Vec<PathBuf> = Vec::new();
    if let Ok(text) = std::fs::read_to_string(user_path) {
        trusted_projects = trusted_projects_from(&text);
        load_scope(
            &text,
            Scope::User,
            user_path,
            None,
            &mut by_id,
            &mut diagnostics,
        );
    }

    if let Ok(text) = std::fs::read_to_string(project_path) {
        let trusted = trusted_projects
            .iter()
            .any(|p| paths_match(p, project_root));
        load_scope(
            &text,
            Scope::Project,
            project_path,
            Some(trusted),
            &mut by_id,
            &mut diagnostics,
        );
    }

    let profiles = by_id.into_values().collect();
    (profiles, diagnostics)
}

fn paths_match(a: &Path, b: &Path) -> bool {
    fn canon_or_lexical(p: &Path) -> PathBuf {
        p.canonicalize().unwrap_or_else(|_| p.to_path_buf())
    }
    canon_or_lexical(a) == canon_or_lexical(b)
}

/// `trusted_projects = ["<abs path>", ...]` at the top level of the user profiles file.
/// A parse failure here is reported separately by `load_scope`'s own parse of the same text.
fn trusted_projects_from(text: &str) -> Vec<PathBuf> {
    let root: toml::Value = match toml::from_str(text) {
        Ok(v) => v,
        Err(_) => return Vec::new(),
    };
    root.as_table()
        .and_then(|t| t.get("trusted_projects"))
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str())
                .map(PathBuf::from)
                .collect()
        })
        .unwrap_or_default()
}

/// Parse one scope's file text, validate each `[[profile]]` entry independently, and insert
/// valid ones into `by_id` (later scopes overwrite earlier ones with the same `id`).
///
/// `project_trust` is `None` for built-in/user scopes (scripts always allowed) and
/// `Some(trusted)` for project scope.
fn load_scope(
    text: &str,
    scope: Scope,
    file: &Path,
    project_trust: Option<bool>,
    by_id: &mut BTreeMap<String, Profile>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let root: toml::Value = match toml::from_str(text) {
        Ok(v) => v,
        Err(e) => {
            diagnostics.push(Diagnostic::new(None, file, format!("invalid TOML: {e}")));
            return;
        }
    };
    let Some(table) = root.as_table() else {
        diagnostics.push(Diagnostic::new(None, file, "root is not a table"));
        return;
    };
    let entries = table
        .get("profile")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();

    for entry in entries {
        match parse_entry(&entry, scope, file) {
            Ok((mut profile, test_diagnostics)) => {
                if scope == Scope::Project && profile.script.is_some() {
                    let trusted = project_trust.unwrap_or(false);
                    if !trusted {
                        profile.script = None;
                        diagnostics.push(Diagnostic::new(
                            Some(profile.id.clone()),
                            file,
                            "script dropped: project is not listed in trusted_projects",
                        ));
                    }
                }
                for reason in test_diagnostics {
                    diagnostics.push(Diagnostic::new(Some(profile.id.clone()), file, reason));
                }
                by_id.insert(profile.id.clone(), profile);
            }
            Err((profile_id, reason)) => {
                diagnostics.push(Diagnostic::new(profile_id, file, reason));
            }
        }
    }
}

type EntryError = (Option<String>, String);

fn parse_entry(
    entry: &toml::Value,
    scope: Scope,
    file: &Path,
) -> Result<(Profile, Vec<String>), EntryError> {
    let table = entry
        .as_table()
        .ok_or_else(|| (None, "profile entry is not a table".to_string()))?;

    let id = table
        .get("id")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
        .ok_or_else(|| (None, "missing or empty `id`".to_string()))?;

    let match_spec = optional_entry_field(table, "match", &id, parse_match)?;
    let sections = optional_entry_field(table, "sections", &id, parse_sections)?;
    let merge_small = parse_merge_small(table, &id)?;
    let preview = optional_entry_field(table, "preview", &id, parse_preview)?;
    let script = parse_script(table, &id)?;
    let (tests, test_diagnostics) = parse_tests(table);

    Ok((
        Profile {
            id,
            scope,
            file: file.to_path_buf(),
            match_spec,
            sections,
            merge_small,
            preview,
            script,
            tests,
        },
        test_diagnostics,
    ))
}

fn optional_entry_field<T>(
    table: &toml::map::Map<String, toml::Value>,
    key: &str,
    id: &str,
    parse: impl FnOnce(&toml::Value) -> Result<T, String>,
) -> Result<Option<T>, EntryError> {
    table
        .get(key)
        .map(parse)
        .transpose()
        .map_err(|error| (Some(id.to_string()), error))
}

fn parse_merge_small(
    table: &toml::map::Map<String, toml::Value>,
    id: &str,
) -> Result<bool, EntryError> {
    match table.get("merge_small") {
        None => Ok(true),
        Some(value) => value.as_bool().ok_or_else(|| {
            (
                Some(id.to_string()),
                "merge_small must be a bool".to_string(),
            )
        }),
    }
}

fn parse_script(
    table: &toml::map::Map<String, toml::Value>,
    id: &str,
) -> Result<Option<String>, EntryError> {
    match table.get("script") {
        None => Ok(None),
        Some(value) => value
            .as_str()
            .map(|script| Some(script.to_string()))
            .ok_or_else(|| (Some(id.to_string()), "script must be a string".to_string())),
    }
}

fn parse_tests(table: &toml::map::Map<String, toml::Value>) -> (Vec<ProfileTest>, Vec<String>) {
    let mut diagnostics = Vec::new();
    let tests = table
        .get("test")
        .and_then(|value| value.as_array())
        .map(|entries| {
            entries
                .iter()
                .filter_map(|entry| match parse_test(entry) {
                    Ok(test) => Some(test),
                    Err(reason) => {
                        diagnostics.push(reason);
                        None
                    }
                })
                .collect()
        })
        .unwrap_or_default();
    (tests, diagnostics)
}

fn parse_match(v: &toml::Value) -> Result<MatchSpec, String> {
    let table = v.as_table().ok_or("`match` must be a table")?;
    let command = table.get("command").and_then(|v| v.as_str());
    let source = table.get("source").and_then(|v| v.as_str());
    match (command, source) {
        (Some(pat), None) => Ok(MatchSpec::Command(GlobPattern::compile(pat)?)),
        (None, Some(pat)) => Ok(MatchSpec::Source(GlobPattern::compile(pat)?)),
        (Some(_), Some(_)) => Err("`match` must set exactly one of `command` or `source`".into()),
        (None, None) => Err("`match` must set `command` or `source`".into()),
    }
}

fn parse_sections(v: &toml::Value) -> Result<SectionsSpec, String> {
    let table = v.as_table().ok_or("`sections` must be a table")?;
    let heading = table.get("heading").and_then(|v| v.as_str());
    let start = table.get("start").and_then(|v| v.as_str());
    let jsonl_key = table.get("jsonl_key").and_then(|v| v.as_str());
    let set = [heading.is_some(), start.is_some(), jsonl_key.is_some()]
        .iter()
        .filter(|b| **b)
        .count();
    if set != 1 {
        return Err("`sections` must set exactly one of `heading`, `start`, or `jsonl_key`".into());
    }
    if let Some(pat) = heading {
        return Regex::new(pat)
            .map(SectionsSpec::Heading)
            .map_err(|e| format!("bad `sections.heading` regex: {e}"));
    }
    if let Some(pat) = start {
        return Regex::new(pat)
            .map(SectionsSpec::Start)
            .map_err(|e| format!("bad `sections.start` regex: {e}"));
    }
    Ok(SectionsSpec::JsonlKey(jsonl_key.unwrap().to_string()))
}

fn parse_preview(v: &toml::Value) -> Result<PreviewSpec, String> {
    let table = v.as_table().ok_or("`preview` must be a table")?;
    let kind = match table.get("kind").and_then(|v| v.as_str()) {
        Some("toc") => PreviewKind::Toc,
        Some("head") => PreviewKind::Head,
        Some(other) => {
            return Err(format!(
                "`preview.kind` must be \"toc\" or \"head\", got {other:?}"
            ))
        }
        None => return Err("`preview.kind` is required".into()),
    };
    let items_per_section = match table.get("items_per_section") {
        None => None,
        Some(v) => Some(
            v.as_integer()
                .and_then(|n| usize::try_from(n).ok())
                .ok_or("`preview.items_per_section` must be a non-negative integer")?,
        ),
    };
    let item = match table.get("item") {
        None => None,
        Some(v) => {
            let pat = v.as_str().ok_or("`preview.item` must be a string")?;
            Some(Regex::new(pat).map_err(|e| format!("bad `preview.item` regex: {e}"))?)
        }
    };
    Ok(PreviewSpec {
        kind,
        items_per_section,
        item,
    })
}

/// A malformed `[[profile.test]]` case is skipped, not fatal to the profile, but reported as a
/// diagnostic (mirrors code-cli's rule-test convention).
fn parse_test(v: &toml::Value) -> Result<ProfileTest, String> {
    let table = v
        .as_table()
        .ok_or("profile.test entry is not a table".to_string())?;
    let name = table
        .get("name")
        .and_then(|v| v.as_str())
        .ok_or("profile.test entry missing string `name`".to_string())?
        .to_string();
    let input = table
        .get("input")
        .and_then(|v| v.as_str())
        .ok_or_else(|| format!("profile.test `{name}` missing string `input`"))?
        .to_string();
    let expect_records = table.get("expect_records").cloned();
    let expect_preview_contains = table
        .get("expect_preview_contains")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default();
    Ok(ProfileTest {
        name,
        input,
        expect_records,
        expect_preview_contains,
    })
}

/// Translate a glob pattern (`*`, `?`, `[...]`, `[!...]`) to an anchored regex.
fn glob_to_regex(pattern: &str) -> Result<Regex, String> {
    let mut re = String::from("^");
    let mut chars = pattern.chars().peekable();
    while let Some(c) = chars.next() {
        match c {
            '*' => re.push_str(".*"),
            '?' => re.push('.'),
            '[' => append_glob_class(&mut re, &mut chars, pattern)?,
            c if "\\.+^$()|{}".contains(c) => {
                re.push('\\');
                re.push(c);
            }
            c => re.push(c),
        }
    }
    re.push('$');
    Regex::new(&re).map_err(|e| format!("bad glob {pattern:?}: {e}"))
}

fn append_glob_class(
    re: &mut String,
    chars: &mut std::iter::Peekable<std::str::Chars<'_>>,
    pattern: &str,
) -> Result<(), String> {
    re.push('[');
    if chars.peek() == Some(&'!') {
        chars.next();
        re.push('^');
    }
    for c in chars.by_ref() {
        re.push(c);
        if c == ']' {
            return Ok(());
        }
    }
    Err(format!("unterminated `[` in glob {pattern:?}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write(dir: &tempfile::TempDir, name: &str, contents: &str) -> PathBuf {
        let path = dir.path().join(name);
        std::fs::write(&path, contents).unwrap();
        path
    }

    #[test]
    fn missing_files_load_empty_without_diagnostics() {
        let dir = tempfile::tempdir().unwrap();
        let user = dir.path().join("nope-user.toml");
        let project = dir.path().join("nope-project.toml");
        let (profiles, diagnostics) = load_from_paths(&user, &project, dir.path());
        // Only embedded built-in profiles load when user/project files are absent.
        assert_eq!(profiles.len(), 4);
        assert_eq!(profiles[0].scope, Scope::Builtin);
        assert!(diagnostics.is_empty());
    }

    #[test]
    fn valid_entry_loads_and_malformed_entry_is_reported() {
        let dir = tempfile::tempdir().unwrap();
        let user = write(
            &dir,
            "profiles.toml",
            r#"
[[profile]]
id = "cargo-test"
match = { command = "cargo test*" }
merge_small = false

[[profile]]
match = { command = "no-id*" }
"#,
        );
        let project = dir.path().join("no-project.toml");
        let (profiles, diagnostics) = load_from_paths(&user, &project, dir.path());

        // Plus the embedded built-in profile ("cargo-test" sorts first by id).
        assert_eq!(profiles.len(), 5);
        assert_eq!(profiles[0].id, "cargo-test");
        assert!(!profiles[0].merge_small);
        assert_eq!(profiles[0].scope, Scope::User);
        match &profiles[0].match_spec {
            Some(MatchSpec::Command(g)) => {
                assert!(g.is_match("cargo test --workspace"));
                assert!(!g.is_match("cargo build"));
            }
            other => panic!("expected Command match spec, got {other:?}"),
        }

        assert_eq!(diagnostics.len(), 1);
        assert_eq!(diagnostics[0].profile_id, None);
        assert!(diagnostics[0].reason.contains("id"));
    }

    #[test]
    fn malformed_test_case_is_skipped_and_reported_without_dropping_the_profile() {
        let dir = tempfile::tempdir().unwrap();
        let user = write(
            &dir,
            "profiles.toml",
            r#"
[[profile]]
id = "cargo-test"
match = { command = "cargo test*" }

[[profile.test]]
name = "good case"
input = "ok\n"

[[profile.test]]
input = "missing a name\n"
"#,
        );
        let project = dir.path().join("no-project.toml");
        let (profiles, diagnostics) = load_from_paths(&user, &project, dir.path());

        // Plus the embedded built-in profile ("cargo-test" sorts first by id).
        assert_eq!(profiles.len(), 5);
        assert_eq!(profiles[0].id, "cargo-test");
        assert_eq!(profiles[0].tests.len(), 1);
        assert_eq!(profiles[0].tests[0].name, "good case");

        assert_eq!(diagnostics.len(), 1);
        assert_eq!(diagnostics[0].profile_id.as_deref(), Some("cargo-test"));
        assert!(diagnostics[0].reason.contains("name"), "{diagnostics:?}");
    }

    #[test]
    fn later_scope_overrides_by_id() {
        let dir = tempfile::tempdir().unwrap();
        let user = write(
            &dir,
            "profiles.toml",
            r#"
[[profile]]
id = "shared"
merge_small = true
"#,
        );
        let project = write(
            &dir,
            "toz-profiles.toml",
            r#"
[[profile]]
id = "shared"
merge_small = false
"#,
        );
        let (profiles, diagnostics) = load_from_paths(&user, &project, dir.path());
        assert!(diagnostics.is_empty());
        // Plus the embedded built-in profile ("shared" sorts first by id).
        assert_eq!(profiles.len(), 5);
        assert_eq!(profiles[0].id, "shared");
        assert_eq!(profiles[0].scope, Scope::Project);
        assert!(!profiles[0].merge_small);
    }

    #[test]
    fn untrusted_project_script_is_dropped_with_diagnostic() {
        let dir = tempfile::tempdir().unwrap();
        let user = write(&dir, "profiles.toml", "");
        let project = write(
            &dir,
            "toz-profiles.toml",
            r#"
[[profile]]
id = "proj"
script = "toz.record('x', {})"
"#,
        );
        let (profiles, diagnostics) = load_from_paths(&user, &project, dir.path());
        // Plus the embedded built-in profile ("proj" sorts first by id).
        assert_eq!(profiles.len(), 5);
        assert_eq!(profiles[0].id, "proj");
        assert_eq!(profiles[0].script, None);
        assert_eq!(diagnostics.len(), 1);
        assert_eq!(diagnostics[0].profile_id, Some("proj".to_string()));
        assert!(diagnostics[0].reason.contains("trusted_projects"));
    }

    #[test]
    fn trusted_project_keeps_script() {
        let dir = tempfile::tempdir().unwrap();
        let project_root = dir.path().join("myproj");
        std::fs::create_dir_all(&project_root).unwrap();
        let user_toml = format!(
            "trusted_projects = [{:?}]\n",
            project_root.to_string_lossy()
        );
        let user = write(&dir, "profiles.toml", &user_toml);
        let project = write(
            &dir,
            "toz-profiles.toml",
            r#"
[[profile]]
id = "proj"
script = "toz.record('x', {})"
"#,
        );
        let (profiles, diagnostics) = load_from_paths(&user, &project, &project_root);
        assert!(diagnostics.is_empty());
        // Plus the embedded built-in profile ("proj" sorts first by id).
        assert_eq!(profiles.len(), 5);
        assert_eq!(profiles[0].id, "proj");
        assert_eq!(profiles[0].script.as_deref(), Some("toz.record('x', {})"));
    }

    #[test]
    fn bad_glob_and_bad_regex_are_diagnosed() {
        let dir = tempfile::tempdir().unwrap();
        let user = write(
            &dir,
            "profiles.toml",
            r#"
[[profile]]
id = "bad-glob"
match = { command = "cargo [test*" }

[[profile]]
id = "bad-regex"
sections = { heading = "^(unterminated" }

[[profile]]
id = "bad-preview-kind"
preview = { kind = "bogus" }
"#,
        );
        let project = dir.path().join("no-project.toml");
        let (profiles, diagnostics) = load_from_paths(&user, &project, dir.path());
        // Every user-scope entry is dropped; only embedded built-in profiles remain.
        assert_eq!(profiles.len(), 4);
        assert_eq!(profiles[0].scope, Scope::Builtin);
        assert_eq!(diagnostics.len(), 3);
        assert!(diagnostics.iter().all(|d| d.profile_id.is_some()));
    }

    #[test]
    fn summarize_json_shape() {
        let dir = tempfile::tempdir().unwrap();
        let user = write(
            &dir,
            "profiles.toml",
            r#"
[[profile]]
id = "cargo-test"
script = "1"
"#,
        );
        let project = dir.path().join("no-project.toml");
        let (profiles, _) = load_from_paths(&user, &project, dir.path());
        // Summarize only the profile under test; the embedded built-in profile also loads.
        let cargo_test: Vec<Profile> = profiles
            .into_iter()
            .filter(|p| p.id == "cargo-test")
            .collect();
        let summaries = summarize(&cargo_test);
        let v = serde_json::to_value(&summaries).unwrap();
        assert_eq!(
            v,
            serde_json::json!([{
                "id": "cargo-test",
                "scope": "user",
                "file": user.display().to_string(),
                "has_script": true,
            }])
        );
    }

    #[test]
    fn malformed_root_is_a_diagnostic_not_a_crash() {
        let dir = tempfile::tempdir().unwrap();
        let user = write(&dir, "profiles.toml", "not valid toml [[[");
        let project = dir.path().join("no-project.toml");
        let (profiles, diagnostics) = load_from_paths(&user, &project, dir.path());
        // The malformed user file is dropped; only embedded built-in profiles remain.
        assert_eq!(profiles.len(), 4);
        assert_eq!(profiles[0].scope, Scope::Builtin);
        assert_eq!(diagnostics.len(), 1);
        assert!(diagnostics[0].reason.contains("invalid TOML"));
    }

    fn test_profile(id: &str, scope: Scope, match_spec: MatchSpec) -> Profile {
        Profile {
            id: id.to_string(),
            scope,
            file: PathBuf::from("<test>"),
            match_spec: Some(match_spec),
            sections: None,
            merge_small: true,
            preview: None,
            script: None,
            tests: Vec::new(),
        }
    }

    #[test]
    fn find_match_prefers_project_scope_over_user_and_builtin() {
        let user = test_profile(
            "user-cargo",
            Scope::User,
            MatchSpec::Command(GlobPattern::compile("cargo *").unwrap()),
        );
        let project = test_profile(
            "project-cargo",
            Scope::Project,
            MatchSpec::Command(GlobPattern::compile("cargo *").unwrap()),
        );
        let profiles = vec![user, project];
        let found = find_match(&profiles, "cargo test --workspace", true).unwrap();
        assert_eq!(found.id, "project-cargo");
    }

    #[test]
    fn find_match_command_ignores_non_command_captures() {
        let profiles = vec![test_profile(
            "cargo",
            Scope::User,
            MatchSpec::Command(GlobPattern::compile("cargo *").unwrap()),
        )];
        assert!(find_match(&profiles, "cargo test", false).is_none());
        assert!(find_match(&profiles, "cargo test", true).is_some());
    }

    #[test]
    fn find_match_source_applies_regardless_of_is_command() {
        let profiles = vec![test_profile(
            "json-files",
            Scope::User,
            MatchSpec::Source(GlobPattern::compile("*.json").unwrap()),
        )];
        assert!(find_match(&profiles, "data.json", false).is_some());
    }

    #[test]
    fn builtin_scope_is_embedded_and_loads_without_diagnostics() {
        assert!(!BUILTIN_PROFILES_TOML.trim().is_empty());
        let dir = tempfile::tempdir().unwrap();
        let user = dir.path().join("no-user.toml");
        let project = dir.path().join("no-project.toml");
        let (profiles, diagnostics) = load_from_paths(&user, &project, dir.path());
        assert!(
            profiles.iter().any(|p| p.id == "varde-code-nav-map"),
            "{profiles:?}"
        );
        assert!(diagnostics.is_empty(), "{diagnostics:?}");
    }
}
