//! Fails when non-test crate sources name a legacy binary in a string literal.
//! Modules call each other in process; self re-exec goes through `current_exe`.

use std::fs;
use std::path::{Path, PathBuf};

const LEGACY_NAMES: [&str; 5] = [
    "varde-code",
    "varde-workflow",
    "varde-toz",
    "varde-learn",
    "toz",
];

/// (file relative to `clis/`, exact literal, reason). Not spawns.
const ALLOWLIST: &[(&str, &str, &str)] = &[
    (
        "workflow/varde-workflow/src/commands/instructions.rs",
        r#"toz"#,
        "skill, feature or section name, not a call",
    ),
    (
        "varde/src/sync/harness.rs",
        r#"toz"#,
        "legacy executable name detection, not a call",
    ),
    (
        "varde-core/src/lib.rs",
        r#"toz note block start marker"#,
        "message, label, or hint text",
    ),
    (
        "varde-core/src/lib.rs",
        r#"toz note block end marker"#,
        "message, label, or hint text",
    ),
    (
        "learn/crates/varde-learn/src/cli.rs",
        r#"varde-learn"#,
        "legacy clap command name",
    ),
    (
        "learn/crates/varde-learn/src/cli.rs",
        r#"varde-learn diagnose capture [OPTIONS] --json"#,
        "message, label, or hint text",
    ),
    (
        "code/crates/varde-code/src/scan_cli.rs",
        r#"toz"#,
        "JSON/config key or script global named toz",
    ),
    (
        "code/crates/varde-code/src/lib.rs",
        r#"varde-code nav_map {repo_root}"#,
        "message, label, or hint text",
    ),
    (
        "code/crates/varde-code/src/toz.rs",
        r#"varde-code results {mode}"#,
        "message, label, or hint text",
    ),
    (
        "code/crates/varde-code/src/toz.rs",
        r#"toz query --handle {handle} --lines {}:{}"#,
        "message, label, or hint text",
    ),
    (
        "code/crates/varde-code/src/toz.rs",
        r#"toz query --handle {handle} \"<term>\""#,
        "message, label, or hint text",
    ),
    (
        "code/crates/varde-code/src/hooks.rs",
        r#"varde-code"#,
        "hook marker value, not a spawn",
    ),
    (
        "code/crates/varde-code/src/hooks.rs",
        r#"varde-code nav_map --json \"{\\\"repoRoot\\\":\\\"$(pwd)\\\"}\" --format text --with-project-knowledge"#,
        "hook command text written to agent config, not run here",
    ),
    (
        "code/crates/varde-code/src/db.rs",
        r#"varde-code"#,
        "sibling of current_exe (self re-exec target)",
    ),
    (
        "code/crates/varde-code/src/watch.rs",
        r#"varde-code watch: watching {}"#,
        "message, label, or hint text",
    ),
    (
        "code/crates/varde-code/src/watch.rs",
        r#"varde-code watch: dropped change event for {} (reconcile loop gone)"#,
        "message, label, or hint text",
    ),
    (
        "code/crates/varde-code/src/watch.rs",
        r#"varde-code watch: warning: failed to read {candidate}: {err}"#,
        "message, label, or hint text",
    ),
    (
        "code/crates/varde-code/src/watch.rs",
        r#"varde-code watch: {}: reconcile panicked ({msg}); continuing"#,
        "message, label, or hint text",
    ),
    (
        "code/crates/varde-code/src/watch.rs",
        r#"varde-code watch: {repo_root}: reconcile failed: {err:#}"#,
        "message, label, or hint text",
    ),
    (
        "code/crates/varde-code/src/watch.rs",
        r#"varde-code watch: cannot create {} to record changed paths for {}: {err}"#,
        "message, label, or hint text",
    ),
    (
        "code/crates/varde-code/src/watch.rs",
        r#"varde-code watch: failed to write changed-paths file {} for {}: {err}"#,
        "message, label, or hint text",
    ),
    (
        "code/crates/varde-code/src/watch.rs",
        r#"varde-code watch: failed to clear readiness: {err}"#,
        "message, label, or hint text",
    ),
    (
        "code/crates/varde-code/src/watch.rs",
        r#"varde-code watch: failed to clean partial registration: {cleanup_err:#}"#,
        "message, label, or hint text",
    ),
    (
        "code/crates/varde-code/src/watch.rs",
        r#"varde-code watch: retaining registration because supervisor stop failed: {stop_err:#}"#,
        "message, label, or hint text",
    ),
    (
        "code/crates/varde-code/src/test_cli.rs",
        r#"toz"#,
        "JSON/config key or script global named toz",
    ),
    (
        "code/crates/varde-code/src/rules/mod.rs",
        r#"varde-code"#,
        "config directory name",
    ),
    (
        "code/crates/varde-code/src/db/path.rs",
        r#"varde-code"#,
        "config directory name",
    ),
    (
        "code/crates/varde-code/src/query/find_pattern.rs",
        r#"toz"#,
        "JSON/config key or script global named toz",
    ),
    (
        "code/crates/varde-code/src/cli.rs",
        r#"varde-code"#,
        "legacy clap command name",
    ),
    (
        "toz/crates/toz-core/src/profile.rs",
        r#"toz"#,
        "config directory name",
    ),
    (
        "toz/crates/toz-core/src/config.rs",
        r#"varde-toz"#,
        "config directory name",
    ),
    (
        "toz/crates/toz-core/src/config.rs",
        r#"toz"#,
        "config directory name",
    ),
    (
        "varde/src/migrate/config_move.rs",
        r#"varde-toz"#,
        "legacy store name, not a binary invocation",
    ),
    (
        "varde/src/migrate/config_move.rs",
        r#"toz"#,
        "legacy store name, not a binary invocation",
    ),
    (
        "varde/src/migrate/legacy_bins.rs",
        r#"varde-code"#,
        "removal probe of a legacy executable, not a call",
    ),
    (
        "varde/src/migrate/legacy_bins.rs",
        r#"varde-workflow"#,
        "removal probe of a legacy executable, not a call",
    ),
    (
        "varde/src/migrate/legacy_bins.rs",
        r#"varde-toz"#,
        "removal probe of a legacy executable, not a call",
    ),
    (
        "varde/src/migrate/legacy_bins.rs",
        r#"toz"#,
        "removal probe of a legacy executable, not a call",
    ),
    (
        "varde/src/migrate/legacy_bins.rs",
        r#"varde-learn"#,
        "removal probe of a legacy executable, not a call",
    ),
    (
        "toz/crates/toz-core/src/project.rs",
        r#"toz"#,
        "JSON/config key or script global named toz",
    ),
    (
        "toz/crates/toz-core/src/script.rs",
        r#"toz"#,
        "JSON/config key or script global named toz",
    ),
    (
        "toz/crates/toz/src/lib.rs",
        r#"toz supports macOS and Linux only (process groups, isatty, and hook plumbing are Unix-specific)"#,
        "message, label, or hint text",
    ),
    (
        "toz/crates/toz/src/lib.rs",
        r#"toz worker: {error:#}"#,
        "message, label, or hint text",
    ),
    (
        "toz/crates/toz/src/worker.rs",
        r#"toz worker exited with {status}"#,
        "message, label, or hint text",
    ),
    (
        "toz/crates/toz/src/worker.rs",
        r#"toz worker: raw capture unavailable: {error:#}"#,
        "message, label, or hint text",
    ),
    (
        "toz/crates/toz/src/commands.rs",
        r#"varde-toz {} at {}"#,
        "message, label, or hint text",
    ),
    (
        "toz/crates/toz/src/commands.rs",
        r#"toz"#,
        "executable-name or legacy-directory comparison, not a spawn",
    ),
    (
        "toz/crates/toz/src/commands.rs",
        r#"varde-toz"#,
        "executable-name or legacy-directory comparison, not a spawn",
    ),
    (
        "toz/crates/toz/src/commands.rs",
        r#"toz run is disabled (set script.enabled = true in config.toml)"#,
        "message, label, or hint text",
    ),
    (
        "toz/crates/toz/src/commands.rs",
        r#"varde-toz run {} #{}"#,
        "message, label, or hint text",
    ),
    (
        "toz/crates/toz/src/install.rs",
        r#"varde-toz"#,
        "executable-name or legacy-directory comparison, not a spawn",
    ),
    (
        "toz/crates/toz/src/install.rs",
        r#"toz"#,
        "executable-name or legacy-directory comparison, not a spawn",
    ),
    (
        "toz/crates/toz/src/sandbox.rs",
        r#"toz sandbox is unsupported on this platform"#,
        "message, label, or hint text",
    ),
    (
        "toz/crates/toz/src/cli.rs",
        r#"varde-toz"#,
        "legacy clap command name",
    ),
    (
        "workflow/md-core/src/memory.rs",
        r#"toz"#,
        "JSON/config key or script global named toz",
    ),
    (
        "workflow/varde-workflow/src/execution_wave.rs",
        r#"varde map unavailable: independence cannot be checked"#,
        "message, label, or hint text",
    ),
    (
        "workflow/varde-workflow/src/commands/instructions.rs",
        r#"varde-workflow instructions: orchestration {key} ignored ({reason}); using {value}"#,
        "message, label, or hint text",
    ),
    (
        "workflow/varde-workflow/src/commands/instructions.rs",
        r#"varde-workflow instructions: cannot read {}: {error}"#,
        "message, label, or hint text",
    ),
    (
        "workflow/varde-workflow/src/commands/instructions.rs",
        r#"varde-workflow instructions: {} contains a legacy varde-toz block; run `varde setup sync` to remove it"#,
        "message, label, or hint text",
    ),
    (
        "workflow/varde-workflow/src/commands/instructions.rs",
        r#"varde-workflow instructions: could not write {}: {error}"#,
        "message, label, or hint text",
    ),
    (
        "workflow/varde-workflow/src/commands/instructions.rs",
        r#"varde-toz"#,
        "PATH lookup only; the executable is never launched",
    ),
    (
        "workflow/varde-workflow/src/commands/paths.rs",
        r#"toz"#,
        "JSON/config key or script global named toz",
    ),
    (
        "workflow/varde-workflow/src/cli.rs",
        r#"varde-workflow"#,
        "legacy clap command name",
    ),
    (
        "varde/src/hooks_install.rs",
        r#"varde-workflow"#,
        "executable-name comparison for a legacy hook command, not a spawn",
    ),
    (
        "varde/src/hooks_install.rs",
        r#"toz"#,
        "skill, feature or section name, not a call",
    ),
    (
        "varde/src/sync/config.rs",
        r#"toz"#,
        "skill, feature or section name, not a call",
    ),
    (
        "varde/src/sync/skills.rs",
        r#"varde-toz"#,
        "skill, feature or section name, not a call",
    ),
    (
        "varde/src/sync/skills.rs",
        r#"toz"#,
        "skill, feature or section name, not a call",
    ),
    (
        "varde/src/sync/skills.rs",
        r#"varde-learn"#,
        "skill, feature or section name, not a call",
    ),
    (
        "varde/src/sync/skills.rs",
        r#"varde-code"#,
        "skill, feature or section name, not a call",
    ),
    (
        "varde/src/sync/mod.rs",
        r#"toz"#,
        "skill, feature or section name, not a call",
    ),
    (
        "varde/src/migrate/harness.rs",
        r#"varde-workflow"#,
        "executable-name comparison for a legacy hook command, not a spawn",
    ),
    (
        "varde/src/migrate/harness.rs",
        r#"varde-code"#,
        "executable-name comparison for a legacy hook command, not a spawn",
    ),
];

struct Literal {
    line: usize,
    text: String,
    /// True when the literal is the direct argument of `Command::new(`.
    spawn: bool,
}

/// Returns true when the literal is a legacy name or begins a command with one.
fn names_legacy_binary(text: &str) -> bool {
    LEGACY_NAMES.iter().any(|name| {
        text.strip_prefix(name)
            .is_some_and(|rest| rest.is_empty() || rest.starts_with(' '))
    })
}

/// Lists string literals outside comments and inline `#[cfg(test)]` blocks.
fn non_test_literals(source: &str) -> Vec<Literal> {
    let chars: Vec<char> = source.chars().collect();
    let mut out = Vec::new();
    let (mut i, mut line) = (0, 1);
    let mut cfg_test_pending = false;
    let mut skip_depth: Option<usize> = None;
    let mut depth = 0usize;
    while i < chars.len() {
        let c = chars[i];
        let next = chars.get(i + 1).copied();
        if c == '\n' {
            line += 1;
        } else if c == '/' && next == Some('/') {
            while i < chars.len() && chars[i] != '\n' {
                i += 1;
            }
            continue;
        } else if c == '/' && next == Some('*') {
            i += 2;
            while i + 1 < chars.len() && !(chars[i] == '*' && chars[i + 1] == '/') {
                line += usize::from(chars[i] == '\n');
                i += 1;
            }
            i += 2;
            continue;
        } else if c == '\'' {
            // Char literal such as '"' or '\n'; otherwise a lifetime.
            if next == Some('\\') {
                i += 2;
                while i < chars.len() && chars[i] != '\'' {
                    i += 1;
                }
            } else if chars.get(i + 2) == Some(&'\'') {
                i += 2;
            }
        } else if c == '"' || is_raw_string_start(&chars, i) {
            let start_line = line;
            let (text, end, newlines) = read_string(&chars, i);
            line += newlines;
            if skip_depth.is_none() {
                out.push(Literal {
                    line: start_line,
                    text,
                    spawn: is_command_new_argument(&chars[..i]),
                });
            }
            i = end;
            continue;
        } else if c == '#'
            && chars[i..].starts_with(&['#', '[', 'c', 'f', 'g', '(', 't', 'e', 's', 't', ')', ']'])
        {
            cfg_test_pending = true;
        } else if c == ';' {
            cfg_test_pending = false;
        } else if c == '{' {
            depth += 1;
            if cfg_test_pending && skip_depth.is_none() {
                skip_depth = Some(depth);
            }
            cfg_test_pending = false;
        } else if c == '}' {
            if skip_depth == Some(depth) {
                skip_depth = None;
            }
            depth = depth.saturating_sub(1);
        }
        i += 1;
    }
    out
}

/// True when `before` ends with `Command::new(`, ignoring whitespace.
fn is_command_new_argument(before: &[char]) -> bool {
    let trimmed: String = before.iter().collect();
    trimmed.trim_end().ends_with("Command::new(")
}

fn is_raw_string_start(chars: &[char], i: usize) -> bool {
    if chars[i] != 'r' || (i > 0 && (chars[i - 1].is_alphanumeric() || chars[i - 1] == '_')) {
        return false;
    }
    let mut j = i + 1;
    while chars.get(j) == Some(&'#') {
        j += 1;
    }
    chars.get(j) == Some(&'"')
}

/// Reads a normal or raw string starting at `i`; returns (content, next index, newline count).
fn read_string(chars: &[char], i: usize) -> (String, usize, usize) {
    let mut j = i;
    let mut hashes = 0;
    let raw = chars[j] == 'r';
    if raw {
        j += 1;
        while chars[j] == '#' {
            hashes += 1;
            j += 1;
        }
    }
    j += 1; // opening quote
    let mut text = String::new();
    let mut newlines = 0;
    while j < chars.len() {
        let c = chars[j];
        if raw {
            let closes = c == '"' && (1..=hashes).all(|k| chars.get(j + k) == Some(&'#'));
            if closes {
                return (text, j + 1 + hashes, newlines);
            }
        } else if c == '\\' {
            text.push(c);
            j += 1;
            if let Some(&escaped) = chars.get(j) {
                newlines += usize::from(escaped == '\n');
                text.push(escaped);
            }
            j += 1;
            continue;
        } else if c == '"' {
            return (text, j + 1, newlines);
        }
        newlines += usize::from(c == '\n');
        text.push(c);
        j += 1;
    }
    (text, j, newlines)
}

/// Returns `line: literal` messages for each hit not covered by `allow`.
/// A legacy name passed straight to `Command::new(` is never allowlisted.
fn violations(file: &str, source: &str, allow: &[(&str, &str, &str)]) -> Vec<String> {
    non_test_literals(source)
        .into_iter()
        .filter(|lit| names_legacy_binary(&lit.text))
        .filter(|lit| lit.spawn || !allow.iter().any(|(f, t, _)| *f == file && *t == lit.text))
        .map(|lit| format!("{file}:{}: {:?}", lit.line, lit.text))
        .collect()
}

fn clis_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("clis dir")
        .to_path_buf()
}

fn rust_files(dir: &Path, out: &mut Vec<PathBuf>) {
    for entry in fs::read_dir(dir).expect("read dir").flatten() {
        let path = entry.path();
        if path.is_dir() {
            rust_files(&path, out);
        } else if path.extension().is_some_and(|ext| ext == "rs") {
            out.push(path);
        }
    }
}

/// Every `src/` directory of a workspace crate: `<clis>/**/src` outside `target/`.
fn src_dirs(dir: &Path, out: &mut Vec<PathBuf>) {
    for entry in fs::read_dir(dir).expect("read dir").flatten() {
        let path = entry.path();
        let name = entry.file_name();
        if !path.is_dir() || name == "target" || name == "tests" || name == ".git" {
            continue;
        }
        if name == "src" && path.parent().is_some_and(|p| p.join("Cargo.toml").exists()) {
            out.push(path);
        } else {
            src_dirs(&path, out);
        }
    }
}

#[test]
fn fixture_spawns_are_flagged() {
    let fixture = r#"
fn spawn() {
    let _ = ("varde-code", argv);
    Command::new("toz");
    let ok = "varde-learn-output-sbox-";
    // "varde-toz" in a comment
}
#[cfg(test)]
mod tests {
    fn t() { run("varde-workflow"); }
}
fn later() { run("varde-learn status"); }
"#;
    let found = violations("fixture.rs", fixture, &[]);
    assert_eq!(
        found,
        [
            "fixture.rs:3: \"varde-code\"",
            "fixture.rs:4: \"toz\"",
            "fixture.rs:12: \"varde-learn status\"",
        ]
    );
}

#[test]
fn allowlist_matches_file_and_literal_exactly() {
    let source = "const A: &str = \"varde-code\";\n";
    let allow = [("a.rs", "varde-code", "reason")];
    assert!(violations("a.rs", source, &allow).is_empty());
    assert_eq!(violations("b.rs", source, &allow).len(), 1);
}

#[test]
fn allowlist_never_covers_a_command_new_argument() {
    let source = "fn f() {\n    std::process::Command::new(\n        \"varde-code\",\n    );\n    let name = \"varde-code\";\n}\n";
    let allow = [("a.rs", "varde-code", "reason")];
    assert_eq!(
        violations("a.rs", source, &allow),
        ["a.rs:3: \"varde-code\""]
    );
}

#[test]
fn non_test_sources_name_no_legacy_binary() {
    let clis = clis_dir();
    let mut dirs = Vec::new();
    src_dirs(&clis, &mut dirs);
    assert!(
        dirs.len() >= 10,
        "expected every workspace crate src dir, found {dirs:?}"
    );
    let mut found = Vec::new();
    for dir in dirs {
        let mut files = Vec::new();
        rust_files(&dir, &mut files);
        for file in files {
            let rel = file
                .strip_prefix(&clis)
                .expect("under clis")
                .to_string_lossy()
                .into_owned();
            let source = fs::read_to_string(&file).expect("read source");
            found.extend(violations(&rel, &source, ALLOWLIST));
        }
    }
    assert!(
        found.is_empty(),
        "legacy binary names in non-test sources:\n{}",
        found.join("\n")
    );
}
