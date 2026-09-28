//! Runtime accuracy checks for conservative built-in advisories.

use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use ast_grep_language::SupportLang;
use serde_json::Value;
use varde_code::db;
use varde_code::extract;
use varde_code::model::{ExtractOutput, FileMeta};
use varde_code::parse::parse_source;
use varde_code::persist;
use varde_code::resolve;
use varde_code::rules::sql::run_sql_rules;
use varde_code::rules::{Rule, RuleKind, Severity, builtin_rules};

fn rule(id: &str) -> Rule {
    builtin_rules()
        .into_iter()
        .find(|rule| rule.id == id)
        .unwrap_or_else(|| panic!("missing built-in rule {id}"))
}

fn tempdir(tag: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time follows epoch")
        .as_nanos();
    let dir = std::env::temp_dir().join(format!("varde-accuracy-{tag}-{nonce}"));
    std::fs::create_dir_all(&dir).expect("temporary directory creates");
    dir
}

fn metadata(source: &str) -> FileMeta {
    FileMeta {
        mtime: 0,
        size: source.len() as i64,
        content_hash: "0000000000000000".to_string(),
    }
}

fn index_sources(tag: &str, sources: &[(&str, SupportLang, &str)]) -> (PathBuf, PathBuf) {
    let root = tempdir(tag);
    let db_path = root.join("index.db");
    let files: Vec<String> = sources
        .iter()
        .map(|(path, _, _)| (*path).to_string())
        .collect();
    let mut entities = Vec::new();
    let mut symbols = Vec::new();

    for (file_id, (path, language, source)) in sources.iter().enumerate() {
        let parsed = parse_source(language, source);
        assert!(!parsed.has_error(), "{path} fixture must parse cleanly");
        let extracted = extract::extract(&parsed, file_id as u32);
        entities.extend(extracted.entities);
        symbols.extend(extracted.symbols);
    }
    let output = ExtractOutput {
        entities,
        symbols,
        diagnostics: Vec::new(),
        files,
        file_meta: sources
            .iter()
            .map(|(_, _, source)| metadata(source))
            .collect(),
    };
    let graph =
        resolve::resolve(&output.entities, &output.symbols, &output.files).expect("graph resolves");
    persist::persist(&db_path, &[output], &graph, &root).expect("fixture persists");
    (root, db_path)
}

fn run_sql(
    tag: &str,
    sources: &[(&str, SupportLang, &str)],
    ids: &[&str],
) -> Vec<varde_code::rules::finding::Finding> {
    let (root, db_path) = index_sources(tag, sources);
    let connection = db::open_read_only(&db_path).expect("fixture database opens");
    let rules: Vec<Rule> = ids.iter().map(|id| rule(id)).collect();
    let (findings, diagnostics) = run_sql_rules(&rules, &connection).expect("SQL rules run");
    assert!(diagnostics.is_empty(), "SQL diagnostics: {diagnostics:?}");
    drop(connection);
    let _ = std::fs::remove_dir_all(root);
    findings
}

fn findings_for<'a>(
    findings: &'a [varde_code::rules::finding::Finding],
    id: &str,
) -> Vec<&'a varde_code::rules::finding::Finding> {
    findings
        .iter()
        .filter(|finding| finding.rule_id == id)
        .collect()
}

#[test]
fn certified_structural_budgets_are_errors() {
    for id in [
        "fat-interface",
        "too-many-interfaces",
        "deep-inheritance",
        "duplicate-code-clone",
        "file-complexity-hotspot",
        "circular-import",
        "unresolved-local-import",
        "low-fan-in-high-fan-out-file",
    ] {
        assert_eq!(rule(id).severity, Severity::Error, "{id}");
    }
    for id in ["solid-lsp", "solid-isp", "vertical-slice-sprawl"] {
        assert_eq!(rule(id).severity, Severity::Info, "{id}");
    }
}

#[test]
fn relationship_advisories_use_resolved_identity_and_honest_evidence() {
    for id in [
        "solid-lsp",
        "solid-isp",
        "too-many-interfaces",
        "deep-inheritance",
    ] {
        let advisory = rule(id);
        assert_eq!(advisory.kind, RuleKind::Sql, "{id}");
        let query = advisory.query.as_deref().unwrap_or_default();
        assert!(query.contains("resolved_edges"), "{id}: {query}");
    }
    let deep = rule("deep-inheritance");
    assert!(deep.message.contains("at least"));
    assert!(deep.query.unwrap_or_default().contains("max_depth"));
}

#[test]
fn console_log_advisory_keeps_contextual_wording() {
    let console = rule("console-log-strict");
    assert_eq!(console.severity, Severity::Info);
    assert!(console.message.contains("inspect whether"));
    assert!(console.remediation.unwrap_or_default().contains("purpose"));
}

#[test]
fn solid_sql_runs_on_extracted_resolved_and_persisted_sources() {
    let wide_trait = "trait Wide {\n    fn a(&self);\n    fn b(&self);\n    fn c(&self);\n    fn d(&self);\n    fn e(&self);\n    fn f(&self);\n    fn g(&self);\n    fn h(&self);\n}\n\nstruct Narrow;\nimpl Wide for Narrow {\n    fn a(&self) {}\n}\n";
    let rust_contract = "trait RustContract {\n    fn first(&self);\n    fn second(&self) { 1; }\n}\n\nstruct RustService;\nimpl RustContract for RustService {\n    fn first(&self) {}\n}\n";
    let rust_stubs = "trait StubContract {\n    fn a(&self);\n    fn b(&self);\n    fn c(&self);\n    fn d(&self);\n    fn e(&self);\n    fn f(&self);\n    fn g(&self);\n    fn h(&self);\n}\n\nstruct StubService;\nimpl StubContract for StubService {\n    fn a(&self) {}\n    fn b(&self) {}\n    fn c(&self) {}\n}\n\nstruct GetterService;\nimpl StubContract for GetterService {\n    fn a(&self) { self.b(); }\n    fn b(&self) { self.c(); }\n    fn c(&self) { self.d(); }\n    fn d(&self) { self.e(); }\n    fn e(&self) { self.f(); }\n    fn f(&self) { self.g(); }\n    fn g(&self) { self.h(); }\n    fn h(&self) { self.a(); }\n}\n";
    let concise_getters = "interface GetterContract {\n    getA(): number;\n    getB(): number;\n    getC(): number;\n    getD(): number;\n    getE(): number;\n    getF(): number;\n    getG(): number;\n    getH(): number;\n}\nclass GetterNoCall implements GetterContract {\n    getA(): number { return 1; }\n    getB(): number { return 2; }\n    getC(): number { return 3; }\n    getD(): number { return 4; }\n    getE(): number { return 5; }\n    getF(): number { return 6; }\n    getG(): number { return 7; }\n    getH(): number { return 8; }\n}\n";
    let typescript = "interface I1 { a(): void; }\ninterface I2 { b(): void; }\ninterface I3 { c(): void; }\ninterface I4 { d(): void; }\nclass Many implements I1, I2, I3, I4 { a(){} b(){} c(){} d(){} }\n\nclass Big {\n  m01() {} m02() {} m03() {} m04() {}\n  m05() {} m06() {} m07() {} m08() {}\n  m09() {} m10() {} m11() {} m12() {}\n  m13() {} m14() {} m15() {} m16() {}\n}\n\nclass DuplicateFat {\n  m01() {} m02() {} m03() {} m04() {}\n  m05() {} m06() {} m07() {} m08() {}\n  m09() {} m10() {} m11() {} m12() {}\n  m13() {} m14() {} m15() {} m16() {}\n}\nclass DuplicateFat {}\n\nclass Base0 {}\nclass Base1 extends Base0 {}\nclass Base2 extends Base1 {}\nclass Base3 extends Base2 {}\nclass Base4 extends Base3 {}\n";
    let separate_a = "interface Shared { a(): void; }\nclass First implements Shared { a() {} }\n";
    let separate_b = "interface Shared { a(): void; b(): void; }\nclass Second implements Shared { a() {} b() {} }\n";
    let duplicate = "interface DuplicateContract { a(): void; }\nclass DuplicateOwner implements DuplicateContract { a() {} }\nclass DuplicateOwner {}\n";
    let sources = [
        ("src/wide.rs", SupportLang::Rust, wide_trait),
        ("src/rust-contract.rs", SupportLang::Rust, rust_contract),
        ("src/rust-stubs.rs", SupportLang::Rust, rust_stubs),
        (
            "src/concise-getters.ts",
            SupportLang::TypeScript,
            concise_getters,
        ),
        ("src/types.ts", SupportLang::TypeScript, typescript),
        ("src/separate-a.ts", SupportLang::TypeScript, separate_a),
        ("src/separate-b.ts", SupportLang::TypeScript, separate_b),
        ("src/duplicate.ts", SupportLang::TypeScript, duplicate),
    ];
    let findings = run_sql(
        "solid-runtime",
        &sources,
        &[
            "solid-lsp",
            "solid-isp",
            "fat-interface",
            "too-many-interfaces",
            "deep-inheritance",
        ],
    );

    let lsp = findings_for(&findings, "solid-lsp");
    assert_eq!(
        lsp.len(),
        3,
        "wide, RustContract, and StubContract findings"
    );
    let rust_lsp = lsp
        .iter()
        .find(|finding| finding.location.file == "src/rust-contract.rs")
        .expect("Rust impl method span is linked to its struct");
    assert_eq!(rust_lsp.evidence["class_methods"], 1);
    assert_eq!(rust_lsp.evidence["iface_methods"], 2);
    assert_eq!(rust_lsp.severity, Severity::Info);
    assert!(
        rust_lsp
            .message
            .contains("matches 1/2 single-line declarations")
    );

    let isp = findings_for(&findings, "solid-isp");
    assert_eq!(
        isp.len(),
        3,
        "wide, Rust stubs, and concise getters are measured"
    );
    let stubs = isp
        .iter()
        .find(|finding| finding.location.file == "src/rust-stubs.rs")
        .expect("empty Rust stubs are measured");
    assert_eq!(stubs.evidence["class_methods"], 3);
    assert_eq!(stubs.evidence["empty_stubs"], 3);
    let getters = isp
        .iter()
        .find(|finding| finding.location.file == "src/concise-getters.ts")
        .expect("concise getters are measured as short no-call methods");
    assert_eq!(getters.severity, Severity::Info);
    assert_eq!(getters.evidence["class_methods"], 8);
    assert_eq!(getters.evidence["empty_stubs"], 8);
    assert!(
        getters
            .message
            .contains("short methods without indexed calls")
    );
    assert!(isp.iter().all(|finding| {
        finding
            .message
            .contains("short methods without indexed calls")
            && !finding.message.contains("empty bodies")
            && !finding.message.contains("empty stubs")
    }));
    assert!(
        !isp.iter()
            .any(|finding| finding.location.file == "src/rust-stubs.rs"
                && finding.evidence["class_name"] == "GetterService")
    );

    let fat = findings_for(&findings, "fat-interface");
    assert_eq!(fat.len(), 1);
    assert_eq!(fat[0].location.file, "src/types.ts");
    assert_eq!(fat[0].evidence["member_count"], 16);

    let many = findings_for(&findings, "too-many-interfaces");
    assert_eq!(many.len(), 1);
    assert_eq!(many[0].location.file, "src/types.ts");
    assert_eq!(many[0].evidence["implements_count"], 4);

    let deep = findings_for(&findings, "deep-inheritance");
    assert_eq!(deep.len(), 1);
    assert_eq!(deep[0].location.file, "src/types.ts");
    assert_eq!(deep[0].evidence["class_name"], "Base4");
    assert_eq!(deep[0].evidence["chain_depth"], 4);
    assert_eq!(deep[0].evidence["depth_evidence"], "lower_bound");

    assert!(
        findings_for(&findings, "solid-lsp")
            .iter()
            .all(|finding| finding.location.file != "src/separate-a.ts"
                && finding.location.file != "src/separate-b.ts"
                && finding.location.file != "src/duplicate.ts")
    );
}

fn write(path: &Path, source: &str) {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).expect("fixture parent creates");
    }
    std::fs::write(path, source).expect("fixture writes");
}

fn scan_fixture(tag: &str, files: &[(&str, &str)]) -> Value {
    let home = tempdir(&format!("{tag}-home"));
    let repo = tempdir(&format!("{tag}-repo"));
    for (path, source) in files {
        write(&repo.join(path), source);
    }
    let git_init = Command::new("git")
        .args(["init", "-q"])
        .current_dir(&repo)
        .output()
        .expect("git init runs");
    assert!(
        git_init.status.success(),
        "git init failed: {:?}",
        git_init.status
    );
    let build = Command::new(env!("CARGO_BIN_EXE_varde-code"))
        .args(["build", "--repo-root"])
        .arg(&repo)
        .env("HOME", &home)
        .output()
        .expect("build runs");
    assert!(build.status.success(), "build failed: {:?}", build.status);
    let input = format!(r#"{{"repoRoot":"{}"}}"#, repo.display());
    let scan = Command::new(env!("CARGO_BIN_EXE_varde-code"))
        .args(["scan", "--json", &input])
        .env("HOME", &home)
        .output()
        .expect("scan runs");
    assert!(
        scan.status.success(),
        "scan failed: {:?}\n{}",
        scan.status,
        String::from_utf8_lossy(&scan.stderr)
    );
    let payload: Value = serde_json::from_slice(&scan.stdout).expect("scan envelope JSON");
    let _ = std::fs::remove_dir_all(home);
    let _ = std::fs::remove_dir_all(repo);
    payload
}

#[test]
fn console_is_advisory_and_assets_and_uncertified_rust_cycles_do_not_gate() {
    let payload = scan_fixture(
        "runtime-context",
        &[
            (
                "src/app.ts",
                "import icon from './icon.svg';\nexport function render() { console.log(icon); }\n",
            ),
            (".gitignore", "*.svg\n"),
            (
                "src/icon.svg",
                "<svg xmlns=\"http://www.w3.org/2000/svg\" />\n",
            ),
            ("src/a.rs", "use crate::b;\npub fn a() { b::b(); }\n"),
            ("src/b.rs", "use crate::a;\npub fn b() { a::a(); }\n"),
        ],
    );
    assert_eq!(payload["ok"], true);
    let findings = payload["data"]["findings"]
        .as_array()
        .expect("findings array");

    let console: Vec<&Value> = findings
        .iter()
        .filter(|finding| finding["rule_id"] == "console-log-strict")
        .collect();
    assert_eq!(console.len(), 1);
    assert_eq!(console[0]["severity"], "info");
    assert_eq!(
        payload["data"]["rules"]["console-log-strict"]["message"],
        "console.log() call detected; inspect whether this output is intentional"
    );

    let asset: Vec<&Value> = findings
        .iter()
        .filter(|finding| finding["rule_id"] == "unresolved-local-import")
        .collect();
    assert!(asset.is_empty());

    let cycle: Vec<&Value> = findings
        .iter()
        .filter(|finding| finding["rule_id"] == "circular-import")
        .collect();
    assert!(cycle.is_empty());
    assert_eq!(payload["data"]["gate"]["status"], "pass");
}
