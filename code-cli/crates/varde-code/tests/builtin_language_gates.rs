use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use ast_grep_language::SupportLang;
use varde_code::db;
use varde_code::extract;
use varde_code::model::{Diagnostic, EntityKind, ExtractOutput, FileMeta};
use varde_code::parse::{self, SUPPORTED_LANGUAGES};
use varde_code::persist;
use varde_code::resolve;
use varde_code::rules::sql::run_sql_rules;
use varde_code::rules::{Severity, builtin_rules};

#[derive(Clone, Copy)]
struct Fixture {
    name: &'static str,
    extension: &'static str,
    lang: SupportLang,
}

const FIXTURES: &[Fixture] = &[
    Fixture {
        name: "typescript",
        extension: "ts",
        lang: SupportLang::TypeScript,
    },
    Fixture {
        name: "tsx",
        extension: "tsx",
        lang: SupportLang::Tsx,
    },
    Fixture {
        name: "javascript",
        extension: "js",
        lang: SupportLang::JavaScript,
    },
    Fixture {
        name: "c",
        extension: "c",
        lang: SupportLang::C,
    },
    Fixture {
        name: "cpp",
        extension: "cpp",
        lang: SupportLang::Cpp,
    },
    Fixture {
        name: "go",
        extension: "go",
        lang: SupportLang::Go,
    },
    Fixture {
        name: "java",
        extension: "java",
        lang: SupportLang::Java,
    },
    Fixture {
        name: "csharp",
        extension: "cs",
        lang: SupportLang::CSharp,
    },
    Fixture {
        name: "kotlin",
        extension: "kt",
        lang: SupportLang::Kotlin,
    },
    Fixture {
        name: "swift",
        extension: "swift",
        lang: SupportLang::Swift,
    },
    Fixture {
        name: "python",
        extension: "py",
        lang: SupportLang::Python,
    },
    Fixture {
        name: "ruby",
        extension: "rb",
        lang: SupportLang::Ruby,
    },
    Fixture {
        name: "php",
        extension: "php",
        lang: SupportLang::Php,
    },
    Fixture {
        name: "scala",
        extension: "scala",
        lang: SupportLang::Scala,
    },
    Fixture {
        name: "dart",
        extension: "dart",
        lang: SupportLang::Dart,
    },
    Fixture {
        name: "lua",
        extension: "lua",
        lang: SupportLang::Lua,
    },
    Fixture {
        name: "elixir",
        extension: "ex",
        lang: SupportLang::Elixir,
    },
    Fixture {
        name: "solidity",
        extension: "sol",
        lang: SupportLang::Solidity,
    },
    Fixture {
        name: "haskell",
        extension: "hs",
        lang: SupportLang::Haskell,
    },
    Fixture {
        name: "bash",
        extension: "sh",
        lang: SupportLang::Bash,
    },
    Fixture {
        name: "rust",
        extension: "rs",
        lang: SupportLang::Rust,
    },
];

fn source(f: Fixture, decisions: usize) -> String {
    if f.lang == SupportLang::Haskell {
        return format!("f a =\n{}  0\n", "    if a then 1 else\n".repeat(decisions));
    }
    let (prefix, branch, suffix) = match f.lang {
        SupportLang::Go => (
            "package sample\nfunc f(a bool) {\n",
            "    if a { work() }\n",
            "}\n",
        ),
        SupportLang::Python => ("def f(a):\n", "    if a:\n        work()\n", ""),
        SupportLang::Ruby => ("def f(a)\n", "  if a\n    work()\n  end\n", "end\n"),
        SupportLang::Lua => (
            "function f(a)\n",
            "  if a then\n    work()\n  end\n",
            "end\n",
        ),
        SupportLang::Elixir => (
            "defmodule Sample do\n  def f(a) do\n",
            "    if a, do: work()\n",
            "  end\nend\n",
        ),
        SupportLang::Bash => ("f() {\n", "  if true; then work; fi\n", "}\n"),
        SupportLang::TypeScript | SupportLang::Tsx => {
            ("function f(a: boolean) {\n", "    if (a) work();\n", "}\n")
        }
        SupportLang::JavaScript => ("function f(a) {\n", "    if (a) work();\n", "}\n"),
        SupportLang::C => ("void f(int a) {\n", "    if (a) work();\n", "}\n"),
        SupportLang::Cpp => ("void f(bool a) {\n", "    if (a) work();\n", "}\n"),
        SupportLang::Java => (
            "class Sample { void f(boolean a) {\n",
            "    if (a) work();\n",
            "} }\n",
        ),
        SupportLang::CSharp => (
            "class Sample { void f(bool a) {\n",
            "    if (a) work();\n",
            "} }\n",
        ),
        SupportLang::Kotlin => ("fun f(a: Boolean) {\n", "    if (a) work()\n", "}\n"),
        SupportLang::Swift => ("func f(_ a: Bool) {\n", "    if a { work() }\n", "}\n"),
        SupportLang::Php => ("<?php function f($a) {\n", "    if ($a) work();\n", "}\n"),
        SupportLang::Scala => (
            "object Sample { def f(a: Boolean): Unit = {\n",
            "    if (a) work()\n",
            "} }\n",
        ),
        SupportLang::Dart => ("void f(bool a) {\n", "    if (a) work();\n", "}\n"),
        SupportLang::Solidity => (
            "contract Sample { function f(bool a) public {\n",
            "    if (a) work();\n",
            "} }\n",
        ),
        SupportLang::Rust => ("fn f(a: bool) {\n", "    if a { work(); }\n", "}\n"),
        SupportLang::Haskell
        | SupportLang::Css
        | SupportLang::Hcl
        | SupportLang::Html
        | SupportLang::Json
        | SupportLang::Markdown
        | SupportLang::Yaml
        | SupportLang::Nix => unreachable!(),
    };
    format!("{prefix}{body}{suffix}", body = branch.repeat(decisions))
}

fn metadata(text: &str) -> FileMeta {
    FileMeta {
        mtime: 0,
        size: text.len() as i64,
        content_hash: "0000000000000000".into(),
    }
}
fn temp_db() -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "varde-language-gates-{}",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&dir).unwrap();
    dir.join("index.db")
}

fn persist_cases(cases: &[(String, Fixture, String)]) -> PathBuf {
    let mut entities = Vec::new();
    let mut symbols = Vec::new();
    let mut files = Vec::new();
    let mut file_meta = Vec::new();
    let mut diagnostics = Vec::new();
    for (file_id, (path, fixture, text)) in cases.iter().enumerate() {
        let parsed = parse::parse_source(&fixture.lang, text);
        if path.contains("_malformed.") {
            assert!(
                parsed.has_error(),
                "{path} malformed fixture must report syntax error"
            );
        } else {
            assert!(!parsed.has_error(), "{path} clean fixture must parse");
        }
        let extracted = extract::extract(&parsed, file_id as u32);
        assert!(
            extracted
                .entities
                .iter()
                .any(|e| e.kind == EntityKind::Function),
            "{path} function retained"
        );
        if parsed.has_error() {
            diagnostics.push(Diagnostic {
                file_id: Some(file_id as u32),
                path: path.clone(),
                message: "syntax error — partial extract kept".into(),
                severity: "warning".into(),
            });
        }
        entities.extend(extracted.entities);
        symbols.extend(extracted.symbols);
        files.push(path.clone());
        file_meta.push(metadata(text));
    }
    let graph = resolve::resolve(&entities, &symbols, &files).expect("graph resolves");
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
    .unwrap();
    db_path
}

#[test]
fn certified_file_budget_covers_every_extraction_language() {
    let cases: Vec<_> = FIXTURES
        .iter()
        .map(|fixture| {
            let decisions = if fixture.lang == SupportLang::Haskell {
                10
            } else {
                51
            };
            (
                format!("src/file_budget_{}.{}", fixture.name, fixture.extension),
                *fixture,
                source(*fixture, decisions),
            )
        })
        .collect();
    let path = persist_cases(&cases);
    let conn = db::open_read_only(&path).unwrap();
    let rule = builtin_rules()
        .into_iter()
        .find(|rule| rule.id == "file-complexity-hotspot")
        .unwrap();
    let (findings, diagnostics) = run_sql_rules(&[rule], &conn).unwrap();
    assert!(diagnostics.is_empty(), "{diagnostics:?}");
    assert_eq!(findings.len(), FIXTURES.len());
    for (file, fixture, _) in &cases {
        let finding = findings
            .iter()
            .find(|finding| &finding.location.file == file)
            .unwrap_or_else(|| panic!("missing file gate for {}", fixture.name));
        assert_eq!(finding.severity, Severity::Error);
        let expected = if fixture.lang == SupportLang::Haskell {
            55
        } else {
            51
        };
        assert_eq!(finding.evidence["complexity"], expected, "{}", fixture.name);
        assert_eq!(finding.evidence["functions"], 1, "{}", fixture.name);
    }
    drop(conn);
    std::fs::remove_dir_all(path.parent().unwrap()).unwrap();
}

#[test]
fn every_language_hits_real_gate_and_advisory_confidence_paths() {
    assert_eq!(FIXTURES.len(), SUPPORTED_LANGUAGES.len());
    let fixture_languages: HashSet<_> = FIXTURES.iter().map(|fixture| fixture.lang).collect();
    let registered_languages: HashSet<_> = SUPPORTED_LANGUAGES.iter().copied().collect();
    let fixture_names: HashSet<_> = FIXTURES.iter().map(|fixture| fixture.name).collect();
    assert_eq!(
        fixture_languages.len(),
        FIXTURES.len(),
        "duplicate fixture language"
    );
    assert_eq!(
        registered_languages.len(),
        SUPPORTED_LANGUAGES.len(),
        "duplicate registry language"
    );
    assert_eq!(
        fixture_names.len(),
        FIXTURES.len(),
        "duplicate fixture name"
    );
    assert_eq!(
        fixture_languages, registered_languages,
        "fixture and registry languages differ"
    );
    for fixture in FIXTURES {
        assert!(SUPPORTED_LANGUAGES.contains(&fixture.lang));
    }
    for fixture in FIXTURES {
        let mut cases = Vec::new();
        let boundary_decisions = if fixture.lang == SupportLang::Haskell {
            5
        } else {
            15
        };
        let violating_decisions = if fixture.lang == SupportLang::Haskell {
            6
        } else {
            16
        };
        for (label, decisions) in [
            ("compliant", 1),
            ("boundary", boundary_decisions),
            ("violating", violating_decisions),
        ] {
            cases.push((
                format!("src/gates/{}_{}.{}", fixture.name, label, fixture.extension),
                *fixture,
                source(*fixture, decisions),
            ));
        }
        let mut malformed = source(*fixture, violating_decisions);
        malformed.push_str("\n\"");
        cases.push((
            format!("src/gates/{}_malformed.{}", fixture.name, fixture.extension),
            *fixture,
            malformed,
        ));
        let db_path = persist_cases(&cases);
        let conn = db::open_incremental(&db_path).unwrap();
        let (findings, diagnostics) = run_sql_rules(
            &builtin_rules()
                .into_iter()
                .filter(|r| r.id.starts_with("function-complexity-"))
                .collect::<Vec<_>>(),
            &conn,
        )
        .unwrap();
        assert!(diagnostics.is_empty(), "{}: {diagnostics:?}", fixture.name);
        let path =
            |label: &str| format!("src/gates/{}_{}.{}", fixture.name, label, fixture.extension);
        let gate = |p: &str| {
            findings
                .iter()
                .any(|f| f.rule_id == "function-complexity-gate" && f.location.file == p)
        };
        let advisory = |p: &str| {
            findings
                .iter()
                .any(|f| f.rule_id == "function-complexity-advisory" && f.location.file == p)
        };
        let boundary_path = path("boundary");
        let compliant_path = path("compliant");
        let violating_path = path("violating");
        assert!(!gate(&compliant_path));
        assert!(!gate(&boundary_path), "{} boundary gated", fixture.name);
        assert!(
            gate(&violating_path),
            "{} violating not gated",
            fixture.name
        );
        let malformed = format!("src/gates/{}_malformed.{}", fixture.name, fixture.extension);
        assert!(!gate(&malformed));
        assert!(
            advisory(&malformed),
            "{} malformed advisory missing",
            fixture.name
        );
        assert!(!advisory(&compliant_path));
        assert!(!advisory(&boundary_path));
        let metric = |path: &str| {
            conn.query_row(
                "SELECT confidence, cyclomatic, cognitive, line_span, confidence_reasons
                 FROM function_metrics fm JOIN files f ON f.id=fm.file_id
                 WHERE f.path=?1",
                [path],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, i64>(1)?,
                        row.get::<_, i64>(2)?,
                        row.get::<_, i64>(3)?,
                        row.get::<_, String>(4)?,
                    ))
                },
            )
            .unwrap_or_else(|error| panic!("missing metric for {path}: {error}"))
        };
        let compliant_metric = metric(&compliant_path);
        let boundary_metric = metric(&boundary_path);
        let violating_metric = metric(&violating_path);
        assert_eq!(compliant_metric.0, "high");
        assert_eq!(boundary_metric.0, "high");
        assert_eq!(violating_metric.0, "high");
        let expected_boundary = if fixture.lang == SupportLang::Haskell {
            (6, 15)
        } else {
            (16, 15)
        };
        let expected_violation = if fixture.lang == SupportLang::Haskell {
            (7, 21)
        } else {
            (17, 16)
        };
        assert_eq!(
            (boundary_metric.1, boundary_metric.2),
            expected_boundary,
            "{} boundary metric",
            fixture.name
        );
        assert_eq!(
            (violating_metric.1, violating_metric.2),
            expected_violation,
            "{} violating metric",
            fixture.name
        );
        assert!(
            violating_metric.3 <= 60,
            "{} violation should isolate cognitive complexity",
            fixture.name
        );
        let gate_finding = findings
            .iter()
            .find(|finding| {
                finding.rule_id == "function-complexity-gate"
                    && finding.location.file == violating_path
            })
            .unwrap();
        assert_eq!(gate_finding.severity, Severity::Error);
        assert_eq!(gate_finding.evidence["cognitive"], violating_metric.2);
        assert_eq!(gate_finding.evidence["cyclomatic"], violating_metric.1);
        assert_eq!(gate_finding.evidence["line_span"], violating_metric.3);
        assert_eq!(gate_finding.evidence["max_cognitive"], 15.0);
        let advisory_finding = findings
            .iter()
            .find(|finding| {
                finding.rule_id == "function-complexity-advisory"
                    && finding.location.file == malformed
            })
            .unwrap();
        assert_eq!(advisory_finding.severity, Severity::Info);
        let malformed_metric = metric(&malformed);
        assert_eq!(malformed_metric.0, "low");
        assert!(malformed_metric.4.contains("syntax_diagnostic"));
        drop(conn);
        std::fs::remove_dir_all(db_path.parent().unwrap()).unwrap();
    }
}

#[test]
fn cli_scan_exit_code_matches_cross_language_gate() {
    let root = std::env::temp_dir().join(format!("varde-cli-gates-{}", std::process::id()));
    let src = root.join("src");
    std::fs::create_dir_all(&src).unwrap();
    for fixture in [FIXTURES[0], FIXTURES[10], FIXTURES[20]] {
        std::fs::write(
            src.join(format!("gate.{}", fixture.extension)),
            source(fixture, 16),
        )
        .unwrap();
    }
    let home = std::env::temp_dir().join(format!("varde-cli-home-{}", std::process::id()));
    let user_rules = std::env::temp_dir().join(format!("varde-cli-rules-{}", std::process::id()));
    std::fs::create_dir_all(&home).unwrap();
    std::fs::create_dir_all(&user_rules).unwrap();
    let bin = env!("CARGO_BIN_EXE_varde-code");
    let run = |args: &[&str]| {
        Command::new(bin)
            .env("HOME", &home)
            .env("VARDE_USER_RULES_DIR", &user_rules)
            .args(args)
            .output()
            .unwrap()
    };
    let build = run(&["build", "--repo-root", root.to_str().unwrap(), "--force"]);
    assert!(
        build.status.success(),
        "{}",
        String::from_utf8_lossy(&build.stderr)
    );
    let input = serde_json::json!({"repoRoot": root.to_string_lossy()});
    let input_text = input.to_string();
    let scan = run(&["scan", "--json", &input_text]);
    let payload: serde_json::Value = serde_json::from_slice(&scan.stdout).unwrap();
    assert_eq!(payload["ok"], true);
    assert_eq!(payload["data"]["gate"]["status"], "fail");
    assert_eq!(payload["data"]["gate"]["blocking_findings"], 3);
    assert_eq!(payload["data"]["gate"]["diagnostic_count"], 0);
    assert!(
        !scan.status.success(),
        "{}",
        String::from_utf8_lossy(&scan.stdout)
    );
    for fixture in [FIXTURES[0], FIXTURES[10], FIXTURES[20]] {
        std::fs::write(
            src.join(format!("gate.{}", fixture.extension)),
            source(fixture, 1),
        )
        .unwrap();
    }
    let build = run(&["build", "--repo-root", root.to_str().unwrap(), "--force"]);
    assert!(
        build.status.success(),
        "{}",
        String::from_utf8_lossy(&build.stderr)
    );
    let scan = run(&["scan", "--json", &input_text]);
    let payload: serde_json::Value = serde_json::from_slice(&scan.stdout).unwrap();
    assert!(scan.status.success());
    assert_eq!(payload["ok"], true);
    assert_eq!(payload["data"]["gate"]["status"], "pass");
    assert_eq!(payload["data"]["gate"]["blocking_findings"], 0);
    assert_eq!(payload["data"]["gate"]["diagnostic_count"], 0);
    for fixture in [FIXTURES[0], FIXTURES[10], FIXTURES[20]] {
        let mut malformed = source(fixture, 16);
        malformed.push_str("\n\"");
        std::fs::write(src.join(format!("gate.{}", fixture.extension)), malformed).unwrap();
    }
    let build = run(&["build", "--repo-root", root.to_str().unwrap(), "--force"]);
    assert!(
        build.status.success(),
        "{}",
        String::from_utf8_lossy(&build.stderr)
    );
    let scan = run(&["scan", "--json", &input_text]);
    let payload: serde_json::Value = serde_json::from_slice(&scan.stdout).unwrap();
    assert!(!scan.status.success());
    assert_eq!(payload["ok"], true);
    assert_eq!(payload["data"]["gate"]["status"], "unknown");
    assert_eq!(payload["data"]["analysis"]["status"], "incomplete");
    assert_eq!(payload["data"]["gate"]["diagnostic_count"], 6);
    assert_eq!(
        payload["data"]["diagnostics"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|d| d["rule_id"] == "duplicate-code-clone")
            .count(),
        3
    );
    std::fs::remove_dir_all(root).unwrap();
    std::fs::remove_dir_all(home).unwrap();
    std::fs::remove_dir_all(user_rules).unwrap();
}

#[test]
fn natural_line_span_boundary_uses_shipped_limit() {
    let fixture = FIXTURES
        .iter()
        .find(|f| f.lang == SupportLang::Rust)
        .unwrap();
    let make = |body_lines: usize| {
        let mut text = String::from("fn f() {\n");
        for _ in 0..body_lines {
            text.push_str("    let _value = 1;\n");
        }
        text.push_str("}\n");
        text
    };
    let cases = vec![
        ("src/gates/span60.rs".to_string(), *fixture, make(58)),
        ("src/gates/span61.rs".to_string(), *fixture, make(59)),
    ];
    let db_path = persist_cases(&cases);
    let conn = db::open_incremental(&db_path).unwrap();
    let (findings, diagnostics) = run_sql_rules(
        &builtin_rules()
            .into_iter()
            .filter(|r| r.id.starts_with("function-complexity-"))
            .collect::<Vec<_>>(),
        &conn,
    )
    .unwrap();
    assert!(diagnostics.is_empty(), "{diagnostics:?}");
    let gate = |path: &str| {
        findings
            .iter()
            .any(|f| f.rule_id == "function-complexity-gate" && f.location.file == path)
    };
    assert!(!gate("src/gates/span60.rs"));
    assert!(gate("src/gates/span61.rs"));
    drop(conn);
    std::fs::remove_dir_all(db_path.parent().unwrap()).unwrap();
}
