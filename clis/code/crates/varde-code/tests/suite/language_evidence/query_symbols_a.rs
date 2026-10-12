//! Per-language query evidence for the first eleven fixture languages.

use std::path::{Path, PathBuf};
use varde_code::model::EntityKind;
use varde_code::query;
use super::{index_and_persist, IndexedFixture};

fn index_fixture(language: &str) -> IndexedFixture {
    let fixture_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(language);
    let mut paths = Vec::new();
    collect(&fixture_root, &mut paths);
    paths.sort();
    let mut sources = Vec::new();
    for source_path in paths
        .iter()
        .filter(|p| p.extension().and_then(|e| e.to_str()) != Some("bin"))
    {
        let Ok(source) = std::fs::read_to_string(source_path) else {
            continue;
        };
        let relative = source_path.strip_prefix(&fixture_root).unwrap();
        sources.push((relative.to_string_lossy().into_owned(), source));
    }
    index_and_persist(language, "query_symbols_a", sources)
}

fn collect(dir: &Path, paths: &mut Vec<PathBuf>) {
    for entry in std::fs::read_dir(dir).expect("fixture directory") {
        let path = entry.expect("fixture entry").path();
        if path.is_dir() { collect(&path, paths); } else { paths.push(path); }
    }
}

fn data(fixture: &IndexedFixture, mode: &str, extra: &str) -> serde_json::Value {
    let _guard = crate::ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let input = format!(
        r#"{{"repoRoot":"{}","dbPath":"{}",{extra}}}"#,
        fixture.root.display(),
        fixture.db.display()
    );
    let envelope: serde_json::Value =
        serde_json::from_str(&query::run_mode(mode, &input)).expect("query response JSON");
    assert_eq!(envelope["ok"], true, "{mode}: {envelope}");
    envelope["data"].clone()
}

fn assert_query_modes(language: &str, expected_symbol: &str) {
    let fixture = index_fixture(language);
    let file_id = fixture.symbols.iter().find(|s| s.name == expected_symbol).map(|s| s.file_id)
        .or_else(|| fixture.entities.iter().find(|e| e.name == expected_symbol).map(|e| e.file_id))
        .unwrap_or_else(|| panic!("{language} fixture has named symbol {expected_symbol}"));
    let file = &fixture.files[file_id as usize];
    let relative = Path::new(file)
        .strip_prefix(&fixture.root)
        .unwrap()
        .to_string_lossy();
    let got = data(
        &fixture,
        "get_symbol",
        &format!(r#""name":"{}","filePath":"{}""#, expected_symbol, relative),
    );
    assert_eq!(got["name"], expected_symbol, "get_symbol for {language}");
    let expected_names: std::collections::HashSet<&str> = fixture
        .entities
        .iter()
        .filter(|e| e.file_id == file_id)
        .map(|e| e.name.as_str())
        .chain(
            fixture
                .symbols
                .iter()
                .filter(|s| s.file_id == file_id)
                .map(|s| s.name.as_str()),
        )
        .collect();
    let listed = data(
        &fixture,
        "symbols_in_file",
        &format!(r#""filePath":"{}""#, relative),
    );
    assert!(listed.as_array().unwrap().iter().any(|item| item["name"] == expected_symbol), "expected {expected_symbol} in {language}: {listed}");
    assert!(
        listed
            .as_array()
            .unwrap()
            .iter()
            .all(|item| expected_names.contains(item["name"].as_str().unwrap())),
        "unexpected symbols_in_file name for {language}: {listed}"
    );
    let filtered = data(
        &fixture,
        "filter_symbols",
        &format!(r#""file":"{}""#, relative),
    );
    assert!(filtered.as_array().unwrap().iter().any(|item| item["name"] == expected_symbol), "expected {expected_symbol} in filter_symbols for {language}: {filtered}");
    assert!(
        filtered.as_array().unwrap().iter().all(|item| fixture
            .symbols
            .iter()
            .any(|s| s.name == item["name"].as_str().unwrap())
            || fixture
                .entities
                .iter()
                .any(|e| e.name == item["name"].as_str().unwrap())),
        "unexpected filter_symbols result for {language}: {filtered}"
    );

    let import_file_id = fixture
        .entities
        .iter()
        .find(|e| e.kind == EntityKind::Import)
        .map_or(file_id, |e| e.file_id);
    let import_file = &fixture.files[import_file_id as usize];
    let import_relative = Path::new(import_file)
        .strip_prefix(&fixture.root)
        .unwrap()
        .to_string_lossy();
    let imports = data(
        &fixture,
        "find_imports",
        &format!(r#""filePath":"{}""#, import_relative),
    );
    let expected = fixture
        .graph
        .edges
        .iter()
        .filter(|edge| edge.from == import_file_id && edge.kind == varde_code::resolve::EdgeKind::Import)
        .count();
    assert_eq!(
        imports.as_array().unwrap().len(),
        expected,
        "find_imports for {language}: {imports}"
    );

    if let Some(name) = fixture
        .entities
        .iter()
        .filter(|e| matches!(e.kind, EntityKind::Extends | EntityKind::Implements))
        .filter_map(|edge| {
            edge.enclosing_function
                .as_deref()
                .filter(|name| !name.is_empty())
        })
        .find(|name| {
            fixture.entities.iter().any(|e| {
                e.name == *name && matches!(e.kind, EntityKind::Class | EntityKind::Interface)
            })
        })
    {
        let hierarchy_file_id = fixture
            .entities
            .iter()
            .find(|e| e.name == name && matches!(e.kind, EntityKind::Class | EntityKind::Interface))
            .unwrap()
            .file_id;
        let hierarchy_file = Path::new(&fixture.files[hierarchy_file_id as usize])
            .strip_prefix(&fixture.root)
            .unwrap()
            .to_string_lossy();
        let hierarchy = data(
            &fixture,
            "type_hierarchy",
            &format!(r#""name":"{}","filePath":"{}""#, name, hierarchy_file),
        );
        let parent = fixture.entities.iter().find(|entity| entity.enclosing_function.as_deref() == Some(name) && matches!(entity.kind, EntityKind::Extends | EntityKind::Implements)).map(|entity| entity.name.as_str()).expect("fixture inheritance parent");
        assert_eq!(hierarchy["symbol"]["name"], name, "type_hierarchy seed for {language}: {hierarchy}");
        assert!(hierarchy["hierarchy"].as_array().unwrap().iter().any(|item| item["name"] == parent), "type_hierarchy expected parent {parent} for {language}: {hierarchy}");
    }
}

macro_rules! evidence { ($test:ident, $lang:literal, $symbol:literal) => { #[test] fn $test() { assert_query_modes($lang, $symbol); } }; }
evidence!(typescript, "ts", "Greeter");
evidence!(tsx, "tsx", "TodoItem");
evidence!(javascript, "javascript", "greet");
evidence!(python, "python", "greet");
evidence!(ruby, "ruby", "Greeter");
evidence!(php, "php", "Greeter");
evidence!(lua, "lua", "add");
evidence!(bash, "bash", "greet");
evidence!(elixir, "elixir", "Greeter");
evidence!(haskell, "haskell", "Shape");
evidence!(solidity, "solidity", "Wallet");

macro_rules! no_test_fixture_na {
    ($test:ident, $lang:literal) => {
        #[test]
        fn $test() {
            let fixture = index_fixture($lang);
            assert!(fixture.files.iter().all(|path| !Path::new(path).components().any(|part| matches!(part.as_os_str().to_str(), Some("test" | "tests")))), "N/A tests_for_file for {}: fixtures contain no test-directory paths", $lang);
        }
    };
}
no_test_fixture_na!(typescript_tests_for_file_na, "ts");
no_test_fixture_na!(tsx_tests_for_file_na, "tsx");
no_test_fixture_na!(javascript_tests_for_file_na, "javascript");
no_test_fixture_na!(python_tests_for_file_na, "python");
no_test_fixture_na!(ruby_tests_for_file_na, "ruby");
no_test_fixture_na!(php_tests_for_file_na, "php");
no_test_fixture_na!(lua_tests_for_file_na, "lua");
no_test_fixture_na!(bash_tests_for_file_na, "bash");
no_test_fixture_na!(elixir_tests_for_file_na, "elixir");
no_test_fixture_na!(haskell_tests_for_file_na, "haskell");
no_test_fixture_na!(solidity_tests_for_file_na, "solidity");
