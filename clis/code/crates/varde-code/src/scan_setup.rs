//! Presets and language-aware rule selection for `scan setup`.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use crate::query::ApiError;
use crate::rules::{Rule, RuleKind};

/// The nine warning-default rules that minimal disables and strict raises.
pub const PRESET_RULE_IDS: [&str; 9] = [
    "file-complexity-hotspot",
    "function-complexity-gate",
    "duplicate-code-clone",
    "debug-macro-strict",
    "debug-statement-strict",
    "low-fan-in-high-fan-out-file",
    "fat-interface",
    "too-many-interfaces",
    "deep-inheritance",
];

/// A scan setup preset.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Preset {
    Minimal,
    Balanced,
    Strict,
}

impl Preset {
    /// Parse a preset name used by the JSON and CLI surfaces.
    pub fn parse(name: &str) -> Result<Self, ApiError> {
        match name {
            "minimal" => Ok(Self::Minimal),
            "balanced" => Ok(Self::Balanced),
            "strict" => Ok(Self::Strict),
            _ => Err(ApiError::new(
                "invalid_input",
                format!("unknown preset {name:?}; expected minimal, balanced, or strict"),
            )),
        }
    }

    /// Stable name for this preset.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Minimal => "minimal",
            Self::Balanced => "balanced",
            Self::Strict => "strict",
        }
    }

    fn override_severity(self) -> Option<&'static str> {
        match self {
            Self::Minimal => Some("off"),
            Self::Balanced => None,
            Self::Strict => Some("error"),
        }
    }
}

/// Render the override file for a preset. Balanced uses the built-in defaults
/// and therefore returns `None` instead of an empty file.
pub fn overrides_toml(preset: Preset) -> Option<String> {
    let severity = preset.override_severity()?;
    let mut output = String::new();
    for rule_id in PRESET_RULE_IDS {
        use std::fmt::Write as _;
        writeln!(output, "[rules.{rule_id}]").expect("writing to a String cannot fail");
        writeln!(output, "severity = {severity:?}\n").expect("writing to a String cannot fail");
    }
    Some(output)
}

/// Detect the repository's languages from its index file listing when
/// available, falling back to the same ignored-aware filesystem walk used by
/// the scanner when the index has not been built.
pub fn detect_languages(repo_root: &Path) -> Result<Vec<String>, ApiError> {
    if !repo_root.is_dir() {
        return Err(ApiError::new(
            "invalid_input",
            format!("repoRoot is not a directory: {}", repo_root.display()),
        ));
    }

    let input = serde_json::json!({"repoRoot": repo_root.to_string_lossy()});
    match crate::query::open_db(&input) {
        Ok(connection) => languages_from_index(&connection),
        Err(error) if error.code == "index_missing" => languages_from_filesystem(repo_root),
        Err(error) => Err(error),
    }
}

/// Keep SQL rules for every repository and pattern rules that match one of
/// the detected languages. Unscoped pattern rules remain applicable to every
/// language.
pub fn filter_rules<'a>(rules: &'a [Rule], languages: &[String]) -> Vec<&'a Rule> {
    let detected: BTreeSet<&str> = languages.iter().map(String::as_str).collect();
    rules
        .iter()
        .filter(|rule| {
            if rule.kind == RuleKind::Sql {
                return true;
            }

            let Some(rule_languages) = rule.languages.as_deref() else {
                return true;
            };
            if rule_languages.is_empty() {
                return true;
            }

            rule_languages.iter().any(|name| {
                let name = name.to_ascii_lowercase();
                crate::parse::language_from_name(&name).is_some_and(|language| {
                    detected.contains(crate::parse::language_name(&language))
                })
            })
        })
        .collect()
}

fn languages_from_index(connection: &rusqlite::Connection) -> Result<Vec<String>, ApiError> {
    let mut statement = connection
        .prepare("SELECT path FROM files ORDER BY path")
        .map_err(crate::query::db_err)?;
    let rows = statement
        .query_map([], |row| row.get::<_, String>(0))
        .map_err(crate::query::db_err)?;
    let mut paths = Vec::new();
    for row in rows {
        paths.push(PathBuf::from(row.map_err(crate::query::db_err)?));
    }
    Ok(languages_from_paths(paths))
}

fn languages_from_filesystem(repo_root: &Path) -> Result<Vec<String>, ApiError> {
    let root = repo_root.to_string_lossy();
    let files = crate::scan::list_source_files(root.as_ref()).map_err(|error| {
        ApiError::new(
            "io_error",
            format!("unable to list repository files: {error}"),
        )
    })?;
    Ok(languages_from_paths(
        files.into_iter().map(|file| PathBuf::from(file.path)),
    ))
}

fn languages_from_paths(paths: impl IntoIterator<Item = PathBuf>) -> Vec<String> {
    paths
        .into_iter()
        .filter_map(|path| crate::parse::language_for_path(&path))
        .map(|language| crate::parse::language_name(&language).to_string())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn presets_render_the_expected_override_table() {
        assert!(!PRESET_RULE_IDS.contains(&"dependency-boundary"));
        for (preset, expected_severity) in [(Preset::Minimal, "off"), (Preset::Strict, "error")] {
            let rendered = overrides_toml(preset).expect("writes an override table");
            let parsed: toml::Value = toml::from_str(&rendered).expect("valid TOML");
            let rules = parsed["rules"].as_table().expect("rules table");

            assert_eq!(rules.len(), PRESET_RULE_IDS.len());
            for rule_id in PRESET_RULE_IDS {
                assert_eq!(rules[rule_id]["severity"].as_str(), Some(expected_severity));
            }
        }
        assert!(overrides_toml(Preset::Balanced).is_none());
    }

    #[test]
    fn preset_names_are_validated() {
        for (name, expected) in [
            ("minimal", Preset::Minimal),
            ("balanced", Preset::Balanced),
            ("strict", Preset::Strict),
        ] {
            assert_eq!(Preset::parse(name).expect("known preset"), expected);
        }
        assert_eq!(Preset::parse("unknown").unwrap_err().code, "invalid_input");
    }

    #[test]
    fn language_detection_uses_supported_extensions_and_sorts_names() {
        let paths = [
            "src/main.rs",
            "src/component.TSX",
            "src/app.ts",
            "scripts/tool.PY",
            "Cargo.toml",
        ]
        .into_iter()
        .map(PathBuf::from);

        assert_eq!(
            languages_from_paths(paths),
            ["python", "rust", "tsx", "typescript"]
        );
    }

    #[test]
    fn filtering_keeps_sql_and_only_matching_pattern_rules() {
        let rules = crate::rules::builtin_rules();
        let languages = ["rust".to_string(), "typescript".to_string()];
        let filtered = filter_rules(&rules, &languages);
        let ids: BTreeSet<&str> = filtered.iter().map(|rule| rule.id.as_str()).collect();

        assert!(
            ids.contains("dependency-boundary"),
            "SQL rules always remain"
        );
        assert!(ids.contains("eval-usage"), "TypeScript rule remains");
        assert!(
            !ids.contains("empty-except-block"),
            "Python-only rules are filtered out"
        );
    }
}
