//! Secret values collected from the environment and `.env` files.
//!
//! Values are matched literally by the redactor, so a miss only leaves output
//! unredacted. Reading is therefore fail-open: unreadable or non-UTF-8 files
//! and variables are skipped, and no value or error text is returned or logged.

use super::SecretValue;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

/// A variable name containing any of these marks its value secret.
const SECRET_MARKERS: &[&str] = &[
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "PRIVATE",
];

/// Shortest value worth redacting; shorter values are too common to be secrets.
const MIN_VALUE_LEN: usize = 8;

/// Collect secret-named variables from the process environment.
pub fn from_environment() -> Vec<SecretValue> {
    let values = env::vars_os()
        .filter_map(|(name, value)| {
            let name = name.into_string().ok()?;
            if !is_secret_name(&name) {
                return None;
            }
            keep(name, value.into_string().ok()?)
        })
        .collect();
    sorted_deduped(values)
}

/// Collect the values defined by a `.env`-style file.
///
/// An unreadable, non-UTF-8 or missing file yields no values.
pub fn from_dotenv(path: &Path) -> Vec<SecretValue> {
    let Ok(text) = fs::read_to_string(path) else {
        return Vec::new();
    };
    sorted_deduped(text.lines().filter_map(parse_line).collect())
}

/// Collect the values to redact for the project at `root`: secret-named
/// environment variables plus `.env` and `.env.*` files directly under `root`.
pub fn collect(root: &Path) -> Vec<SecretValue> {
    let mut values = from_environment();
    for path in dotenv_files(root) {
        values.extend(from_dotenv(&path));
    }
    sorted_deduped(values)
}

/// `true` when the variable name marks its value secret.
fn is_secret_name(name: &str) -> bool {
    let upper = name.to_ascii_uppercase();
    SECRET_MARKERS.iter().any(|marker| upper.contains(marker))
}

/// Keep a value worth redacting: named, long enough, and not a common literal.
fn keep(name: String, value: String) -> Option<SecretValue> {
    if name.is_empty() || value.chars().count() < MIN_VALUE_LEN || is_common_literal(&value) {
        return None;
    }
    Some(SecretValue { name, value })
}

/// A literal that is never a secret: `true`, `false`, or a bare number.
fn is_common_literal(value: &str) -> bool {
    matches!(value.to_ascii_lowercase().as_str(), "true" | "false") || value.parse::<f64>().is_ok()
}

/// Parse one `.env` line, skipping comments, blanks and lines without `=`.
fn parse_line(line: &str) -> Option<SecretValue> {
    let line = line.trim();
    if line.is_empty() || line.starts_with('#') {
        return None;
    }
    let line = match line.strip_prefix("export") {
        Some(rest) if rest.starts_with(' ') || rest.starts_with('\t') => rest.trim_start(),
        _ => line,
    };
    let (name, value) = line.split_once('=')?;
    keep(
        name.trim().to_string(),
        strip_comment(value.trim()).to_string(),
    )
}

/// Strip a comment from a value: the text after the closing quote of a quoted
/// value, or from the first `#` that starts the value or follows whitespace. A `#`
/// elsewhere in an unquoted value is part of it.
fn strip_comment(value: &str) -> &str {
    if let Some(quote @ ('"' | '\'')) = value.chars().next() {
        if let Some(end) = value[1..].find(quote) {
            return &value[1..1 + end];
        }
    }
    let mut after_whitespace = true;
    for (index, ch) in value.char_indices() {
        if ch == '#' && after_whitespace {
            return value[..index].trim_end();
        }
        after_whitespace = ch.is_whitespace();
    }
    value
}

/// The `.env` and `.env.*` files directly under `root`, in a stable order.
fn dotenv_files(root: &Path) -> Vec<PathBuf> {
    let Ok(entries) = fs::read_dir(root) else {
        return Vec::new();
    };
    let mut paths: Vec<PathBuf> = entries
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| {
            path.is_file()
                && path
                    .file_name()
                    .and_then(|name| name.to_str())
                    .is_some_and(|name| name == ".env" || name.starts_with(".env."))
        })
        .collect();
    paths.sort();
    paths
}

/// Order by `(name, value)` and drop exact duplicates.
fn sorted_deduped(mut values: Vec<SecretValue>) -> Vec<SecretValue> {
    values.sort_by(|a, b| a.name.cmp(&b.name).then_with(|| a.value.cmp(&b.value)));
    values.dedup();
    values
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::OsString;
    use std::path::PathBuf;
    use std::sync::Mutex;

    static ENV_LOCK: Mutex<()> = Mutex::new(());

    /// Serializes environment mutation and restores saved values on drop.
    struct EnvGuard {
        saved: Vec<(String, Option<OsString>)>,
        _lock: std::sync::MutexGuard<'static, ()>,
    }

    impl EnvGuard {
        fn new() -> Self {
            Self {
                saved: Vec::new(),
                _lock: ENV_LOCK
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner),
            }
        }

        fn set(&mut self, name: &str, value: &str) {
            if !self.saved.iter().any(|(saved, _)| saved == name) {
                self.saved.push((name.to_string(), env::var_os(name)));
            }
            unsafe { env::set_var(name, value) };
        }
    }

    impl Drop for EnvGuard {
        fn drop(&mut self) {
            for (name, value) in self.saved.drain(..) {
                match value {
                    Some(value) => unsafe { env::set_var(&name, value) },
                    None => unsafe { env::remove_var(&name) },
                }
            }
        }
    }

    fn tempdir(label: &str) -> PathBuf {
        let dir = env::temp_dir().join(format!(
            "varde-redact-values-{label}-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).expect("temp dir creates");
        dir
    }

    fn write(path: &Path, contents: &str) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("fixture parent creates");
        }
        fs::write(path, contents).expect("fixture writes");
    }

    fn value(name: &str, value: &str) -> SecretValue {
        SecretValue {
            name: name.into(),
            value: value.into(),
        }
    }

    #[test]
    fn environment_keeps_secret_names_and_skips_short_or_common_values() {
        let mut env_guard = EnvGuard::new();
        env_guard.set("VARDE_TEST_REDACT_TOKEN", "environmenttokenvalue");
        env_guard.set("varde_test_redact_lowercase_password", "lowercasepassword");
        env_guard.set("VARDE_TEST_REDACT_KEY", "abcdefg");
        env_guard.set("VARDE_TEST_REDACT_SECRET", "12345678");
        env_guard.set("VARDE_TEST_REDACT_CREDENTIAL", "true");
        env_guard.set("VARDE_TEST_REDACT_PLAIN", "plainnotsecret");

        let values = from_environment();
        assert!(values.contains(&value("VARDE_TEST_REDACT_TOKEN", "environmenttokenvalue")));
        assert!(values.contains(&value(
            "varde_test_redact_lowercase_password",
            "lowercasepassword"
        )));
        let marked = values
            .iter()
            .filter(|sv| sv.name.to_ascii_uppercase().contains("VARDE_TEST_REDACT"))
            .count();
        assert_eq!(marked, 2);
    }

    #[test]
    fn dotenv_parses_export_quotes_and_skips_comments_short_and_common_values() {
        let dir = tempdir("dotenv");
        let path = dir.join(".env");
        write(
            &path,
            &[
                "# comment line",
                "PLAIN=plainvalue",
                "export EXPORTED=\"exported value\"",
                "SINGLE='singlequoted'",
                "SEVEN=abcdefg",
                "EIGHT=abcdefgh",
                "BOOL=true",
                "NUM=12345678",
                "EMPTY=",
                "NOEQUALS",
                "export\tTABBED=tabbedvalue",
                "\tINDENTED=indentedvalue",
            ]
            .join("\n"),
        );
        assert_eq!(
            from_dotenv(&path),
            vec![
                value("EIGHT", "abcdefgh"),
                value("EXPORTED", "exported value"),
                value("INDENTED", "indentedvalue"),
                value("PLAIN", "plainvalue"),
                value("SINGLE", "singlequoted"),
                value("TABBED", "tabbedvalue"),
            ]
        );
    }

    #[test]
    fn dotenv_strips_trailing_comments_from_quoted_and_unquoted_values() {
        let dir = tempdir("comments");
        let path = dir.join(".env");
        write(
            &path,
            &[
                "UNQUOTED=abcdefghijk123 # prod key",
                "QUOTED=\"zyxwvutsrq987\" # note",
                "SINGLE='singlequoted9' # note",
                "HASH=abcdefghijk123#notacomment",
                "TAB=abcdefghijk123\t# tabbed comment",
            ]
            .join("\n"),
        );
        assert_eq!(
            from_dotenv(&path),
            vec![
                value("HASH", "abcdefghijk123#notacomment"),
                value("QUOTED", "zyxwvutsrq987"),
                value("SINGLE", "singlequoted9"),
                value("TAB", "abcdefghijk123"),
                value("UNQUOTED", "abcdefghijk123"),
            ]
        );
    }

    #[test]
    fn dotenv_treats_a_leading_hash_as_a_comment() {
        let dir = tempdir("leading-hash");
        let path = dir.join(".env");
        write(
            &path,
            &[
                "SPACED= # a long comment that is not a value",
                "TABBED=\t# another long comment value",
            ]
            .join("\n"),
        );
        assert!(from_dotenv(&path).is_empty());
    }

    #[test]
    fn dotenv_missing_or_unreadable_files_are_skipped() {
        let dir = tempdir("missing");
        assert!(from_dotenv(&dir.join("absent.env")).is_empty());
        let binary = dir.join("binary.env");
        fs::write(&binary, [0xff, 0xfe, b'=', b'x']).expect("fixture writes");
        assert!(from_dotenv(&binary).is_empty());
    }

    #[test]
    fn collect_reads_env_and_dotenv_files_directly_under_root() {
        let mut env_guard = EnvGuard::new();
        env_guard.set("VARDE_TEST_COLLECT_TOKEN", "environmenttokenvalue");

        let root = tempdir("collect");
        write(&root.join(".env"), "TOKEN=envfiletokenvalue\n");
        write(
            &root.join(".env.local"),
            "TOKEN=localfiletokenvalue\nTOKEN=envfiletokenvalue\n",
        );
        write(&root.join("sub/.env"), "TOKEN=nestedtokenvalue\n");
        write(&root.join("notes.txt"), "TOKEN=notadotenvfile\n");

        let values = collect(&root);
        assert!(values.contains(&value("TOKEN", "envfiletokenvalue")));
        assert!(values.contains(&value("TOKEN", "localfiletokenvalue")));
        assert!(values.contains(&value("VARDE_TEST_COLLECT_TOKEN", "environmenttokenvalue")));
        assert_eq!(
            values
                .iter()
                .filter(|sv| sv.value == "envfiletokenvalue")
                .count(),
            1
        );
        assert!(!values.iter().any(|sv| sv.value == "nestedtokenvalue"));
        assert!(!values.iter().any(|sv| sv.value == "notadotenvfile"));
        assert!(values.windows(2).all(|pair| {
            (pair[0].name.as_str(), pair[0].value.as_str())
                <= (pair[1].name.as_str(), pair[1].value.as_str())
        }));
        assert_eq!(values, collect(&root));
    }

    #[test]
    fn ordering_dedupes_by_name_then_value() {
        let input = vec![
            value("B", "beta"),
            value("A", "alpha"),
            value("B", "alpha"),
            value("A", "alpha"),
        ];
        assert_eq!(
            sorted_deduped(input),
            vec![value("A", "alpha"), value("B", "alpha"), value("B", "beta"),]
        );
    }
}
