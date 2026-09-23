use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use ast_grep_language::SupportLang;
use varde_code::db;
use varde_code::extract;
use varde_code::model::{Diagnostic, ExtractOutput, FileMeta};
use varde_code::parse::{SUPPORTED_LANGUAGES, parse_source};
use varde_code::{persist, resolve};

const CURRENT_METRIC_VERSION: i64 = 2;

struct Fixture {
    label: &'static str,
    extension: &'static str,
    language: SupportLang,
    source: &'static str,
}

const FIXTURES: &[Fixture] = &[
    Fixture {
        label: "typescript",
        extension: "ts",
        language: SupportLang::TypeScript,
        source: "function f(): void {}\n",
    },
    Fixture {
        label: "tsx",
        extension: "tsx",
        language: SupportLang::Tsx,
        source: "function f(): JSX.Element { return <div />; }\n",
    },
    Fixture {
        label: "javascript",
        extension: "js",
        language: SupportLang::JavaScript,
        source: "function f() {}\n",
    },
    Fixture {
        label: "c",
        extension: "c",
        language: SupportLang::C,
        source: "void f(void) {}\n",
    },
    Fixture {
        label: "cpp",
        extension: "cpp",
        language: SupportLang::Cpp,
        source: "void f() {}\n",
    },
    Fixture {
        label: "go",
        extension: "go",
        language: SupportLang::Go,
        source: "package sample\nfunc f() {}\n",
    },
    Fixture {
        label: "java",
        extension: "java",
        language: SupportLang::Java,
        source: "class Sample { void f() {} }\n",
    },
    Fixture {
        label: "csharp",
        extension: "cs",
        language: SupportLang::CSharp,
        source: "class Sample { void F() {} }\n",
    },
    Fixture {
        label: "kotlin",
        extension: "kt",
        language: SupportLang::Kotlin,
        source: "fun f() {}\n",
    },
    Fixture {
        label: "swift",
        extension: "swift",
        language: SupportLang::Swift,
        source: "func f() {}\n",
    },
    Fixture {
        label: "python",
        extension: "py",
        language: SupportLang::Python,
        source: "def f():\n    pass\n",
    },
    Fixture {
        label: "ruby",
        extension: "rb",
        language: SupportLang::Ruby,
        source: "def f\nend\n",
    },
    Fixture {
        label: "php",
        extension: "php",
        language: SupportLang::Php,
        source: "<?php function f() {}\n",
    },
    Fixture {
        label: "scala",
        extension: "scala",
        language: SupportLang::Scala,
        source: "object Sample { def f(): Unit = () }\n",
    },
    Fixture {
        label: "dart",
        extension: "dart",
        language: SupportLang::Dart,
        source: "void f() {}\n",
    },
    Fixture {
        label: "lua",
        extension: "lua",
        language: SupportLang::Lua,
        source: "function f() end\n",
    },
    Fixture {
        label: "elixir",
        extension: "ex",
        language: SupportLang::Elixir,
        source: "defmodule Sample do\n  def f do\n    :ok\n  end\nend\n",
    },
    Fixture {
        label: "solidity",
        extension: "sol",
        language: SupportLang::Solidity,
        source: "contract Sample { function f() public {} }\n",
    },
    Fixture {
        label: "haskell",
        extension: "hs",
        language: SupportLang::Haskell,
        source: "f x = x\n",
    },
    Fixture {
        label: "bash",
        extension: "sh",
        language: SupportLang::Bash,
        source: "f() { :; }\n",
    },
    Fixture {
        label: "rust",
        extension: "rs",
        language: SupportLang::Rust,
        source: "fn f() {}\n",
    },
];

fn fixture_path(fixture: &Fixture) -> String {
    format!(
        "src/complexity-confidence/{}.{}",
        fixture.label, fixture.extension
    )
}

fn temp_db() -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time follows epoch")
        .as_nanos();
    let dir = std::env::temp_dir().join(format!(
        "varde-function-complexity-{}-{nonce}",
        std::process::id()
    ));
    std::fs::create_dir_all(&dir).expect("temporary directory creates");
    dir.join("index.db")
}

fn metadata(source: &str) -> FileMeta {
    FileMeta {
        mtime: 0,
        size: source.len() as i64,
        content_hash: "0000000000000000".to_string(),
    }
}

#[test]
fn every_supported_language_persists_a_high_confidence_metric() {
    assert_eq!(FIXTURES.len(), SUPPORTED_LANGUAGES.len());
    for language in SUPPORTED_LANGUAGES {
        assert!(
            FIXTURES.iter().any(|fixture| fixture.language == *language),
            "missing fixture for {language:?}"
        );
    }

    let mut entities = Vec::new();
    let mut symbols = Vec::new();
    let mut diagnostics = Vec::new();
    let mut files = Vec::new();
    let mut file_meta = Vec::new();

    for fixture in FIXTURES {
        let file_id = files.len() as u32;
        let parsed = parse_source(&fixture.language, fixture.source);
        assert!(
            !parsed.has_error(),
            "{} fixture must parse cleanly",
            fixture.label
        );
        let extracted = extract::extract(&parsed, file_id);
        assert!(
            extracted
                .entities
                .iter()
                .any(|entity| entity.kind == varde_code::model::EntityKind::Function),
            "{} fixture must emit a function",
            fixture.label
        );
        entities.extend(extracted.entities);
        symbols.extend(extracted.symbols);
        files.push(fixture_path(fixture));
        file_meta.push(metadata(fixture.source));
    }

    let unknown_path = "src/complexity-confidence/unknown.fixture".to_string();
    let unknown_source = "fn advisory() {}\n";
    let unknown_file_id = files.len() as u32;
    let unknown = extract::extract(
        &parse_source(&SupportLang::Rust, unknown_source),
        unknown_file_id,
    );
    entities.extend(unknown.entities);
    symbols.extend(unknown.symbols);
    files.push(unknown_path.clone());
    file_meta.push(metadata(unknown_source));

    let broken_path = "src/complexity-confidence/broken.rs".to_string();
    let broken_source = "fn broken() {}\n@\n";
    let broken_file_id = files.len() as u32;
    let broken = extract::extract(
        &parse_source(&SupportLang::Rust, broken_source),
        broken_file_id,
    );
    assert!(broken.has_error, "broken fixture must report syntax errors");
    assert!(
        broken
            .entities
            .iter()
            .any(|entity| entity.kind == varde_code::model::EntityKind::Function),
        "broken fixture must retain its partial function"
    );
    entities.extend(broken.entities);
    symbols.extend(broken.symbols);
    diagnostics.push(Diagnostic {
        file_id: Some(broken_file_id),
        path: broken_path.clone(),
        message: "syntax error — partial extract kept".to_string(),
        severity: "warning".to_string(),
    });
    files.push(broken_path.clone());
    file_meta.push(metadata(broken_source));

    let graph = resolve::resolve(&entities, &symbols, &files).expect("fixture graph resolves");
    let output = ExtractOutput {
        entities,
        symbols,
        diagnostics,
        files,
        file_meta,
    };
    let db_path = temp_db();
    persist::persist(
        &db_path,
        &[output],
        &graph,
        Path::new(env!("CARGO_MANIFEST_DIR")),
    )
    .expect("fixture metrics persist");

    let connection = db::open_incremental(&db_path).expect("fixture database opens");
    for fixture in FIXTURES {
        let path = fixture_path(fixture);
        let metric: (String, i64) = connection
            .query_row(
                "SELECT fm.confidence, fm.metric_version
                 FROM function_metrics fm
                 JOIN files f ON f.id = fm.file_id
                 WHERE f.path = ?1
                 ORDER BY fm.id
                 LIMIT 1",
                [&path],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .unwrap_or_else(|error| panic!("{} metric missing: {error}", fixture.label));
        assert_eq!(metric.0, "high", "{} confidence", fixture.label);
        assert_eq!(
            metric.1, CURRENT_METRIC_VERSION,
            "{} metric version",
            fixture.label
        );
    }

    let advisory: (String, String, i64) = connection
        .query_row(
            "SELECT fm.confidence, fm.confidence_reasons, fm.metric_version
             FROM function_metrics fm
             JOIN files f ON f.id = fm.file_id
             WHERE f.path = ?1",
            [&unknown_path],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .expect("unknown-extension metric exists");
    assert_eq!(advisory.0, "partial");
    assert!(advisory.1.contains("unsupported_language_profile"));
    assert_eq!(advisory.2, CURRENT_METRIC_VERSION);

    let syntax_error: (String, String, i64) = connection
        .query_row(
            "SELECT fm.confidence, fm.confidence_reasons, fm.metric_version
             FROM function_metrics fm
             JOIN files f ON f.id = fm.file_id
             WHERE f.path = ?1",
            [&broken_path],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .expect("syntax-error metric exists");
    assert_eq!(syntax_error.0, "low");
    assert!(syntax_error.1.contains("syntax_diagnostic"));
    assert_eq!(syntax_error.2, CURRENT_METRIC_VERSION);

    drop(connection);
    std::fs::remove_dir_all(db_path.parent().expect("database has parent"))
        .expect("temporary directory removes");
}
