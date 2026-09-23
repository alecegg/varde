use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use ast_grep_language::SupportLang;
use varde_code::db;
use varde_code::extract;
use varde_code::model::{ExtractOutput, FileMeta};
use varde_code::parse::parse_source;
use varde_code::persist;
use varde_code::resolve;
use varde_code::rules::finding::Finding;
use varde_code::rules::sql::run_sql_rules;
use varde_code::rules::{Rule, builtin_rules};

fn fixture_db(sources: &[(&str, SupportLang, &str)]) -> (PathBuf, PathBuf) {
    let root = std::env::temp_dir().join(format!(
        "varde-structural-gates-{}",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let output = ExtractOutput {
        entities: sources
            .iter()
            .enumerate()
            .flat_map(|(id, (_, lang, source))| {
                let parsed = parse_source(lang, source);
                assert!(!parsed.has_error());
                extract::extract(&parsed, id as u32).entities
            })
            .collect(),
        symbols: Vec::new(),
        diagnostics: Vec::new(),
        files: sources
            .iter()
            .map(|(path, _, _)| (*path).to_string())
            .collect(),
        file_meta: sources
            .iter()
            .map(|(_, _, source)| FileMeta {
                mtime: 0,
                size: source.len() as i64,
                content_hash: "0".into(),
            })
            .collect(),
    };
    let graph = resolve::resolve(&output.entities, &output.symbols, &output.files).unwrap();
    let db_path = root.join("index.db");
    persist::persist(&db_path, &[output], &graph, &root).unwrap();
    (root, db_path)
}

fn run(ids: &[&str], sources: &[(&str, SupportLang, &str)]) -> Vec<Finding> {
    let (root, db_path) = fixture_db(sources);
    let conn = db::open_read_only(&db_path).unwrap();
    let rules: Vec<Rule> = builtin_rules()
        .into_iter()
        .filter(|r| ids.contains(&r.id.as_str()))
        .collect();
    let (findings, diagnostics) = run_sql_rules(&rules, &conn).unwrap();
    assert!(diagnostics.is_empty(), "{diagnostics:?}");
    drop(conn);
    let _ = std::fs::remove_dir_all(root);
    findings
}

fn methods(count: usize) -> String {
    (0..count).map(|i| format!("m{i}() {{}} ")).collect()
}

#[test]
fn structural_budgets_respect_positive_boundary_and_negative_counts() {
    let boundary = format!("class Boundary {{ {} }}", methods(15));
    let positive = format!("class Positive {{ {} }}", methods(16));
    let source = format!("{boundary}\n{positive}");
    let findings = run(
        &["fat-interface"],
        &[("src/policy.ts", SupportLang::TypeScript, &source)],
    );
    assert_eq!(findings.len(), 1);
    assert_eq!(findings[0].evidence["member_count"], 16);
    assert_eq!(findings[0].evidence["threshold"], 15.0);

    let java_methods = (0..15)
        .map(|i| format!("void m{i}() {{}} "))
        .collect::<String>();
    let nested = format!(
        "class Outer {{ {java_methods} static class Inner {{ void a(){{}} void b(){{}} }} }}"
    );
    let findings = run(
        &["fat-interface"],
        &[("src/Nested.java", SupportLang::Java, &nested)],
    );
    assert!(
        findings.is_empty(),
        "nested type members must not inflate Outer"
    );

    let hierarchy = "class A {} class B extends A {} class C extends B {} class D extends C {} class E extends D {}";
    let findings = run(
        &["deep-inheritance"],
        &[("src/policy.ts", SupportLang::TypeScript, hierarchy)],
    );
    assert_eq!(findings.len(), 1);
    assert_eq!(findings[0].evidence["chain_depth"], 4);
}

#[test]
fn structural_counts_do_not_aggregate_same_names_or_nested_types() {
    let source = r#"
        class Same { a(){} b(){} }
        class Outer { a(){} b(){} }
        class Wide { a(){} b(){} c(){} d(){} e(){} f(){} g(){} h(){} i(){} j(){} k(){} l(){} m(){} n(){} o(){} p(){} }
    "#;
    let findings = run(
        &["fat-interface"],
        &[
            ("src/a.ts", SupportLang::TypeScript, source),
            ("src/b.ts", SupportLang::TypeScript, source),
            ("scripts/generated.ts", SupportLang::TypeScript, source),
            ("tests/generated.ts", SupportLang::TypeScript, source),
        ],
    );
    let wide = findings
        .iter()
        .filter(|f| f.rule_id == "fat-interface")
        .collect::<Vec<_>>();
    assert_eq!(wide.len(), 2);
    assert!(wide.iter().all(|f| f.location.file.starts_with("src/")));
    assert!(
        wide.iter()
            .all(|f| f.severity == varde_code::rules::Severity::Error)
    );
}

#[test]
fn interface_budget_counts_real_contracts_only() {
    let source = r#"
        interface I1 { a(): void; }
        interface I2 { b(): void; }
        interface I3 { c(): void; }
        interface I4 { d(): void; }
        interface Marker {}
        class Three implements I1, I2, I3 { a(){} b(){} c(){} }
        class Four implements I1, I2, I3, I4 { a(){} b(){} c(){} d(){} }
        class MarkerOnly implements Marker {}
    "#;
    let findings = run(
        &["too-many-interfaces"],
        &[("src/contracts.ts", SupportLang::TypeScript, source)],
    );
    assert_eq!(findings.len(), 1);
    assert_eq!(findings[0].evidence["class_name"], "Four");
    assert_eq!(findings[0].evidence["implements_count"], 4);
}

#[test]
fn file_budget_uses_certified_actual_functions() {
    let source = (0..6)
        .map(|i| format!("function f{i}(a: boolean) {{ if (a) {{ if (a) {{ if (a) {{ if (a) {{ return; }} }} }} }} }}"))
        .collect::<Vec<_>>()
        .join("\n");
    let findings = run(
        &["file-complexity-hotspot"],
        &[("src/complex.ts", SupportLang::TypeScript, &source)],
    );
    assert_eq!(findings.len(), 1);
    assert_eq!(findings[0].evidence["complexity"], 60);
    assert_eq!(findings[0].evidence["complexity_per_function"], 10.0);
}

fn flat_decisions(counts: &[usize]) -> String {
    counts
        .iter()
        .enumerate()
        .map(|(index, count)| {
            format!(
                "function f{index}(a: boolean) {{ {} }}\n",
                "if (a) { work(); } ".repeat(*count)
            )
        })
        .collect()
}

#[test]
fn file_budget_checks_exact_boundaries_and_mixed_confidence() {
    let total_boundary = flat_decisions(&[10; 5]);
    let average_boundary = flat_decisions(&[7; 8]);
    let mut counts = vec![7; 100];
    counts[0] = 8;
    let just_over_average = flat_decisions(&counts);
    let findings = run(
        &["file-complexity-hotspot"],
        &[
            ("src/total.ts", SupportLang::TypeScript, &total_boundary),
            ("src/average.ts", SupportLang::TypeScript, &average_boundary),
            ("src/over.ts", SupportLang::TypeScript, &just_over_average),
        ],
    );
    assert_eq!(findings.len(), 1);
    assert_eq!(findings[0].location.file, "src/over.ts");
    assert_eq!(findings[0].evidence["complexity"], 701);
    assert_eq!(findings[0].evidence["complexity_per_function"], 7.01);

    let high = flat_decisions(&[10; 6]);
    let (root, path) = fixture_db(&[("src/mixed.ts", SupportLang::TypeScript, &high)]);
    let conn = db::open(&path).unwrap();
    // Exercise the aggregation contract independently of confidence inference.
    conn.execute(
        "UPDATE function_metrics SET confidence = 'low' WHERE name = 'f0'",
        [],
    )
    .unwrap();
    let rule = builtin_rules()
        .into_iter()
        .find(|rule| rule.id == "file-complexity-hotspot")
        .unwrap();
    let (findings, diagnostics) = run_sql_rules(&[rule], &conn).unwrap();
    assert!(diagnostics.is_empty());
    assert!(
        findings.is_empty(),
        "one uncertain function prevents a certified file aggregate"
    );
    drop(conn);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn nested_local_functions_do_not_count_as_methods() {
    let source = format!(
        "class Outer {{ {} m15() {{ function local() {{}} }} }}",
        methods(14)
    );
    let findings = run(
        &["fat-interface"],
        &[("src/nested.ts", SupportLang::TypeScript, &source)],
    );
    assert!(findings.is_empty());
}

#[test]
fn method_budgets_cover_class_and_associated_method_syntax() {
    let cases: &[(SupportLang, &str, &str, &str, &str)] = &[
        (
            SupportLang::Java,
            "java",
            "class Service {",
            "void mINDEX() {}",
            "}",
        ),
        (
            SupportLang::CSharp,
            "cs",
            "class Service {",
            "void mINDEX() {}",
            "}",
        ),
        (
            SupportLang::Cpp,
            "cpp",
            "class Service { public:",
            "void mINDEX() {}",
            "};",
        ),
        (
            SupportLang::Python,
            "py",
            "class Service:\n",
            "    def mINDEX(self):\n        pass\n",
            "",
        ),
        (
            SupportLang::Ruby,
            "rb",
            "class Service\n",
            "def mINDEX\nend\n",
            "end\n",
        ),
        (
            SupportLang::Kotlin,
            "kt",
            "class Service {",
            "fun mINDEX() {}",
            "}",
        ),
        (
            SupportLang::Swift,
            "swift",
            "class Service {",
            "func mINDEX() {}",
            "}",
        ),
        (
            SupportLang::Dart,
            "dart",
            "class Service {",
            "void mINDEX() {}",
            "}",
        ),
        (
            SupportLang::Scala,
            "scala",
            "class Service {",
            "def mINDEX(): Unit = {}",
            "}",
        ),
        (
            SupportLang::Php,
            "php",
            "<?php class Service {",
            "function mINDEX() {}",
            "}",
        ),
        (
            SupportLang::Rust,
            "rs",
            "struct Service; impl Service {",
            "fn mINDEX(&self) {}",
            "}",
        ),
        (
            SupportLang::Go,
            "go",
            "package main\ntype Service struct{}\n",
            "func (s Service) mINDEX() {}",
            "",
        ),
    ];
    for (language, extension, prefix, method, suffix) in cases {
        for count in [15, 16] {
            let body = (0..count)
                .map(|index| method.replace("INDEX", &index.to_string()))
                .collect::<Vec<_>>()
                .join("\n");
            let source = format!("{prefix}\n{body}\n{suffix}");
            let path = format!("src/service.{extension}");
            let findings = run(&["fat-interface"], &[(path.as_str(), *language, &source)]);
            assert_eq!(
                findings.len(),
                usize::from(count > 15),
                "{language:?} count={count}"
            );
            if let Some(finding) = findings.first() {
                assert_eq!(finding.evidence["member_count"], count);
            }
        }
    }
}
