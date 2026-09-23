use ast_grep_language::SupportLang;
use std::path::PathBuf;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};
use varde_code::model::{ExtractOutput, FileMeta};
use varde_code::parse::{SUPPORTED_LANGUAGES, parse_source};
use varde_code::rules::sql::run_sql_rules_in_repo;
use varde_code::rules::{Rule, Severity, builtin_rules};
use varde_code::{db, extract, persist, resolve};

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

struct FixtureDb {
    root: PathBuf,
    db_path: PathBuf,
}
impl FixtureDb {
    fn new(sources: &[(String, SupportLang, String)]) -> Self {
        let root = std::env::temp_dir().join(format!(
            "varde-exact-clones-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let mut entities = Vec::new();
        for (id, (file, lang, text)) in sources.iter().enumerate() {
            let target = root.join(file);
            std::fs::create_dir_all(target.parent().unwrap()).unwrap();
            std::fs::write(target, text).unwrap();
            let parsed = parse_source(lang, text);
            assert!(!parsed.has_error(), "{file}: {text}");
            let extracted = extract::extract(&parsed, id as u32);
            assert!(!extracted.entities.is_empty(), "{file}");
            entities.extend(extracted.entities);
        }
        let output = ExtractOutput {
            entities,
            symbols: vec![],
            diagnostics: vec![],
            files: sources.iter().map(|s| s.0.clone()).collect(),
            file_meta: sources
                .iter()
                .map(|s| FileMeta {
                    mtime: 0,
                    size: s.2.len() as i64,
                    content_hash: "0".into(),
                })
                .collect(),
        };
        let graph = resolve::resolve(&output.entities, &output.symbols, &output.files).unwrap();
        let db_path = root.join("index.db");
        persist::persist(&db_path, &[output], &graph, &root).unwrap();
        Self { root, db_path }
    }
    fn run(
        &self,
        rule: &Rule,
    ) -> (
        Vec<varde_code::rules::finding::Finding>,
        Vec<varde_code::rules::Diagnostic>,
    ) {
        let conn = db::open_read_only(&self.db_path).unwrap();
        run_sql_rules_in_repo(std::slice::from_ref(rule), &conn, &self.root).unwrap()
    }
}
impl Drop for FixtureDb {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}
fn rule() -> Rule {
    builtin_rules()
        .into_iter()
        .find(|r| r.id == "duplicate-code-clone")
        .unwrap()
}
fn copies(
    lang: SupportLang,
    extension: &str,
    text: &str,
    n: usize,
) -> Vec<(String, SupportLang, String)> {
    (0..n)
        .map(|i| (format!("src/copy{i}.{extension}"), lang, text.to_owned()))
        .collect()
}
fn ts() -> String {
    format!(
        "function f(value: number) {{\n{}    return value + 17;\n}}\n",
        "    work(value);\n".repeat(8)
    )
}
#[test]
fn exact_clones_cover_every_extraction_language() {
    assert_eq!(FIXTURES.len(), SUPPORTED_LANGUAGES.len());
    assert_eq!(rule().severity, Severity::Error);
    for f in FIXTURES {
        let src = source(*f, 9);
        let db = FixtureDb::new(&copies(f.lang, f.extension, &src, 3));
        let (findings, diagnostics) = db.run(&rule());
        assert!(diagnostics.is_empty(), "{}: {diagnostics:?}", f.name);
        assert_eq!(findings.len(), 3, "{}: {findings:?}", f.name);
        assert!(
            findings
                .iter()
                .all(|f| f.evidence["verification"] == "exact-clone")
        );
        assert_eq!(findings[0].evidence["label"], findings[2].evidence["label"]);
    }
}
#[test]
fn literals_operators_identifier_case_and_indentation_are_significant() {
    for replacement in [
        "return value - 17",
        "return value + 18",
        "return Value + 17",
    ] {
        let src = ts();
        let mut files = copies(SupportLang::TypeScript, "ts", &src, 3);
        files[2].2 = src.replace("return value + 17", replacement);
        let (findings, diagnostics) = FixtureDb::new(&files).run(&rule());
        assert!(diagnostics.is_empty());
        assert!(findings.is_empty(), "{replacement}: {findings:?}");
    }
    let src = format!(
        "def f(value):\n{}    if value:\n        work(value)\n    finish(value)\n",
        "    work(value)\n".repeat(8)
    );
    let mut files = copies(SupportLang::Python, "py", &src, 3);
    files[2].2 = src.replace("    finish(value)", "        finish(value)");
    let (findings, diagnostics) = FixtureDb::new(&files).run(&rule());
    assert!(diagnostics.is_empty());
    assert!(findings.is_empty());
}
#[test]
fn comments_spacing_and_function_names_do_not_change_supported_bodies() {
    for (lang, ext, src, rename) in [
        (SupportLang::TypeScript, "ts", ts(), "function renamed("),
        (
            SupportLang::Rust,
            "rs",
            format!(
                "fn f(value: i32) {{\n{}    consume(value + 17);\n}}\n",
                "    work(value);\n".repeat(8)
            ),
            "fn renamed(",
        ),
        (
            SupportLang::Python,
            "py",
            format!(
                "def f(value):\n{}    return value + 17\n",
                "    work(value)\n".repeat(8)
            ),
            "def renamed(",
        ),
    ] {
        let mut files = copies(lang, ext, &src, 3);
        files[1].2 = src.replacen(
            if ext == "ts" {
                "function f("
            } else if ext == "rs" {
                "fn f("
            } else {
                "def f("
            },
            rename,
            1,
        );
        let comment = if ext == "py" {
            "    # explanation\n"
        } else {
            "    // explanation\n"
        };
        files[2].2 = src
            .replacen("    work", &format!("{comment}    work"), 1)
            .replace("value + 17", "value  +  17");
        let (findings, diagnostics) = FixtureDb::new(&files).run(&rule());
        assert!(diagnostics.is_empty(), "{ext}: {diagnostics:?}");
        assert_eq!(findings.len(), 3, "{ext}: {findings:?}");
    }
}
#[test]
fn thresholds_and_candidate_filters_control_verified_groups() {
    let db = FixtureDb::new(&copies(SupportLang::TypeScript, "ts", &ts(), 2));
    assert!(db.run(&rule()).0.is_empty());
    let mut custom = rule();
    custom
        .thresholds
        .as_mut()
        .unwrap()
        .insert("min_members".into(), 2.0);
    assert_eq!(db.run(&custom).0.len(), 2);
    custom
        .thresholds
        .as_mut()
        .unwrap()
        .insert("min_tokens".into(), 10000.0);
    assert!(db.run(&custom).0.is_empty());
    let mut custom = rule();
    custom
        .thresholds
        .as_mut()
        .unwrap()
        .insert("min_span_lines".into(), 100.0);
    let db = FixtureDb::new(&copies(SupportLang::TypeScript, "ts", &ts(), 3));
    assert!(db.run(&custom).0.is_empty());
    let mut custom = rule();
    custom.query = Some(format!(
        "{} AND f.path <> 'src/copy2.ts'",
        custom.query.unwrap()
    ));
    assert!(
        db.run(&custom).0.is_empty(),
        "SQL filtering must precede verification"
    );
}
#[test]
fn separate_groups_with_identical_spans_have_distinct_stable_labels() {
    let mut files = copies(SupportLang::TypeScript, "ts", &ts(), 3);
    files.extend(
        copies(SupportLang::TypeScript, "ts", &ts().replace("17", "18"), 3)
            .into_iter()
            .map(|(p, l, s)| (p.replace("copy", "other"), l, s)),
    );
    let db = FixtureDb::new(&files);
    let (first, diagnostics) = db.run(&rule());
    assert!(diagnostics.is_empty());
    assert_eq!(first.len(), 6);
    let labels: std::collections::HashSet<_> = first
        .iter()
        .map(|f| f.evidence["label"].as_str().unwrap())
        .collect();
    assert_eq!(labels.len(), 2);
    let (second, _) = db.run(&rule());
    assert_eq!(
        serde_json::to_value(first).unwrap(),
        serde_json::to_value(second).unwrap()
    );
}
#[test]
fn unavailable_or_malformed_sources_emit_diagnostics() {
    for malformed in [false, true] {
        let db = FixtureDb::new(&copies(SupportLang::TypeScript, "ts", &ts(), 3));
        if malformed {
            std::fs::write(db.root.join("src/copy0.ts"), "function { broken").unwrap();
        } else {
            std::fs::remove_file(db.root.join("src/copy0.ts")).unwrap();
        }
        let (findings, diagnostics) = db.run(&rule());
        assert!(findings.is_empty());
        assert!(!diagnostics.is_empty());
    }
}
#[test]
fn default_cli_gate_and_local_suppression_preserve_other_members() {
    let db = FixtureDb::new(&copies(SupportLang::TypeScript, "ts", &ts(), 3));
    let home = db.root.join("home");
    std::fs::create_dir_all(&home).unwrap();
    let scan = || {
        let output = Command::new(env!("CARGO_BIN_EXE_varde-code"))
            .args([
                "scan",
                "--json",
                &serde_json::json!({"repoRoot": db.root}).to_string(),
            ])
            .env("HOME", &home)
            .env("VARDE_USER_RULES_DIR", home.join("empty-rules"))
            .output()
            .unwrap();
        let payload: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
        assert!(!output.status.success(), "{payload}");
        assert_eq!(payload["data"]["gate"]["status"], "fail", "{payload}");
        payload
    };
    let payload = scan();
    let clones: Vec<_> = payload["data"]["findings"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|f| f["rule_id"] == "duplicate-code-clone")
        .collect();
    assert_eq!(clones.len(), 1);
    assert_eq!(
        clones[0]["evidence"]["members"].as_array().unwrap().len(),
        3
    );
    assert_eq!(clones[0]["evidence"]["verification"], "exact-clone");
    std::fs::write(
        db.root.join("src/copy0.ts"),
        format!(
            "// varde-ignore-file duplicate-code-clone -- intentional adapter\n{}",
            ts()
        ),
    )
    .unwrap();
    let payload = scan();
    let clones: Vec<_> = payload["data"]["findings"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|f| f["rule_id"] == "duplicate-code-clone")
        .collect();
    assert_eq!(clones.len(), 1);
    assert_eq!(
        clones[0]["evidence"]["members"].as_array().unwrap().len(),
        2
    );
}

#[test]
fn cli_preserves_nested_exact_groups_with_identical_line_ranges() {
    let source = format!("function outer() {{ {} }}\n", ts().trim());
    let db = FixtureDb::new(&copies(SupportLang::TypeScript, "ts", &source, 3));
    let home = db.root.join("home");
    std::fs::create_dir_all(&home).unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_varde-code"))
        .args([
            "scan",
            "--json",
            &serde_json::json!({"repoRoot": db.root}).to_string(),
        ])
        .env("HOME", &home)
        .env("VARDE_USER_RULES_DIR", home.join("empty-rules"))
        .output()
        .unwrap();
    let payload: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(payload["data"]["gate"]["status"], "fail", "{payload}");
    let clones: Vec<_> = payload["data"]["findings"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|finding| finding["rule_id"] == "duplicate-code-clone")
        .collect();
    assert_eq!(
        clones.len(),
        2,
        "outer and inner groups stay distinct: {payload}"
    );
    assert_ne!(
        clones[0]["evidence"]["group"],
        clones[1]["evidence"]["group"]
    );
    for clone in clones {
        let evidence = &clone["evidence"];
        assert_eq!(evidence["verification"], "exact-clone");
        assert!(evidence["token_count"].as_u64().unwrap() >= 20);
        assert_eq!(evidence["min_tokens"], 20);
        assert_eq!(evidence["min_members"], 3);
        assert_eq!(evidence["min_span_lines"], 8);
        assert_eq!(evidence["members"].as_array().unwrap().len(), 3);
        assert_eq!(evidence["bands"].as_array().unwrap().len(), 1);
    }
}

#[test]
fn exact_budget_boundaries_and_literal_whitespace_are_preserved() {
    for (lines, expected) in [(8, 0), (9, 3)] {
        let src = format!(
            "function f(value: number) {{\n{}    return value + 17;\n}}\n",
            "    work(value);\n".repeat(lines - 3)
        );
        let db = FixtureDb::new(&copies(SupportLang::TypeScript, "ts", &src, 3));
        let (findings, diagnostics) = db.run(&rule());
        assert!(diagnostics.is_empty());
        assert_eq!(findings.len(), expected, "{lines} lines");
    }
    let db = FixtureDb::new(&copies(SupportLang::TypeScript, "ts", &ts(), 3));
    let count = db.run(&rule()).0[0].evidence["token_count"]
        .as_u64()
        .unwrap();
    let mut custom = rule();
    custom
        .thresholds
        .as_mut()
        .unwrap()
        .insert("min_tokens".into(), count as f64);
    assert_eq!(db.run(&custom).0.len(), 3);
    custom
        .thresholds
        .as_mut()
        .unwrap()
        .insert("min_tokens".into(), (count + 1) as f64);
    assert!(db.run(&custom).0.is_empty());
    let src = ts().replace("value + 17", "\"literal space\"");
    let mut files = copies(SupportLang::TypeScript, "ts", &src, 3);
    files[2].2 = src.replace("literal space", "literal  space");
    assert!(FixtureDb::new(&files).run(&rule()).0.is_empty());
}

#[test]
fn same_file_occurrences_count_but_test_paths_do_not() {
    let src = format!(
        "{}{}{}",
        ts(),
        ts().replace("function f(", "function g("),
        ts().replace("function f(", "function h(")
    );
    let db = FixtureDb::new(&[("src/module.ts".into(), SupportLang::TypeScript, src.clone())]);
    assert_eq!(db.run(&rule()).0.len(), 3);
    let db = FixtureDb::new(&[("tests/module.test.ts".into(), SupportLang::TypeScript, src)]);
    assert!(db.run(&rule()).0.is_empty());
}
