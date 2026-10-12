use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use serde::Deserialize;
use varde_code::complexity::counts_toward_file_complexity;
use varde_code::{extract, parse};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Golden {
    file: Vec<FileComplexity>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct FileComplexity {
    path: String,
    complexity: u32,
}

fn fixtures_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures")
}

fn golden() -> Golden {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/complexity/legacy_file_complexity.toml");
    toml::from_str(&fs::read_to_string(path).expect("golden fixture reads"))
        .expect("golden fixture parses")
}

fn source_paths(directory: &Path, output: &mut Vec<PathBuf>) {
    let entries = fs::read_dir(directory).expect("fixture directory reads");
    for entry in entries {
        let entry = entry.expect("fixture entry reads");
        let path = entry.path();
        if path.is_dir() {
            // Conformance suites are new-semantics fixtures; only `legacy/` is golden.
            let conformance_suite = path
                .parent()
                .is_some_and(|parent| parent.ends_with("fixtures/complexity"))
                && !path.ends_with("legacy");
            if !conformance_suite {
                source_paths(&path, output);
            }
        } else if parse::language_for_path(&path).is_some() {
            output.push(path);
        }
    }
}

fn file_complexity(path: &Path) -> u32 {
    let bytes = fs::read(path).expect("fixture source reads");
    let Ok(source) = std::str::from_utf8(&bytes) else {
        // The legacy scanner skips non-UTF-8 input, leaving no ControlFlow rows.
        return 1;
    };
    let language = parse::language_for_path(path).expect("fixture extension has a parser");
    let parsed = parse::parse_source(&language, source);
    let entities = extract::extract(&parsed, 0).entities;
    1 + entities
        .iter()
        .filter(|entity| counts_toward_file_complexity(entity))
        .count() as u32
}

#[test]
fn legacy_file_complexity_golden() {
    let root = fixtures_root();
    let golden = golden();
    for path in [
        "complexity/legacy/bash_else.sh",
        "complexity/legacy/lua_else.lua",
        "complexity/legacy/c_goto.c",
        "complexity/legacy/cpp_goto.cpp",
        "complexity/legacy/lua_goto.lua",
        "complexity/legacy/csharp_when.cs",
    ] {
        let path = root.join(path);
        let source = fs::read_to_string(&path).expect("legacy source reads");
        let language = parse::language_for_path(&path).expect("legacy source language resolves");
        let parsed = parse::parse_source(&language, &source);
        assert!(
            !parsed.has_error(),
            "legacy source has a parse error: {}",
            path.display()
        );
    }

    let mut expected_paths = BTreeSet::new();
    for entry in &golden.file {
        assert!(
            expected_paths.insert(entry.path.clone()),
            "duplicate golden path {}",
            entry.path
        );
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests")
            .join(&entry.path);
        assert!(
            path.is_file(),
            "golden source is missing: {}",
            path.display()
        );
        assert_eq!(
            file_complexity(&path),
            entry.complexity,
            "legacy files.complexity changed for {}",
            entry.path
        );
    }

    let mut actual_paths = Vec::new();
    source_paths(&root, &mut actual_paths);
    let actual_paths: BTreeSet<_> = actual_paths
        .iter()
        .map(|path| {
            path.strip_prefix(root.parent().unwrap())
                .unwrap()
                .to_string_lossy()
                .into_owned()
        })
        .collect();
    let missing: Vec<_> = actual_paths.difference(&expected_paths).cloned().collect();
    assert!(
        missing.is_empty(),
        "source fixtures missing from golden: {missing:?}"
    );
}
