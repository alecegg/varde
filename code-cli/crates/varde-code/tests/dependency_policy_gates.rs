use serde_json::Value;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
static NEXT_REPO: AtomicUsize = AtomicUsize::new(0);

struct Repo {
    root: PathBuf,
}
impl Repo {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "varde-dependency-policy-{}-{}-{}",
            NEXT_REPO.fetch_add(1, Ordering::Relaxed),
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        Self { root }
    }
    fn write(&self, path: &str, content: &str) {
        let file = self.root.join(path);
        std::fs::create_dir_all(file.parent().unwrap()).unwrap();
        std::fs::write(file, content).unwrap();
    }
    fn command(&self, command: &str, extra: Value) -> (bool, Value) {
        let mut input = extra;
        input["repoRoot"] = serde_json::json!(self.root);
        let output = Command::new(env!("CARGO_BIN_EXE_varde-code"))
            .args([command, "--json", &input.to_string()])
            .env("HOME", self.root.join("home"))
            .env("VARDE_USER_RULES_DIR", self.root.join("empty-user-rules"))
            .output()
            .unwrap();
        let payload = serde_json::from_slice(&output.stdout).unwrap_or_else(|_| {
            panic!(
                "{}\n{}",
                String::from_utf8_lossy(&output.stdout),
                String::from_utf8_lossy(&output.stderr)
            )
        });
        (output.status.success(), payload)
    }
    fn scan(&self) -> Value {
        let (_, payload) = self.command("scan", serde_json::json!({}));
        assert_eq!(payload["ok"], true, "{payload}");
        assert!(
            payload["data"]["diagnostics"]
                .as_array()
                .unwrap()
                .is_empty(),
            "{payload}"
        );
        payload
    }
    fn fan_limit(&self, limit: usize) {
        self.write(
            ".varde-code/rules/fan.toml",
            &include_str!("../src/rules/builtin/low_fan_in_high_fan_out_file.toml")
                .replace("min_fan_out = 15.0", &format!("min_fan_out = {limit}.0")),
        );
    }
    fn boundary(&self, source: &str, target: &str) {
        self.write(
            ".varde-code/rules/boundary.toml",
            &include_str!("../src/rules/builtin/dependency_boundary.toml")
                .replace(
                    "source_prefix = \"\"",
                    &format!("source_prefix = {source:?}"),
                )
                .replace(
                    "target_prefix = \"\"",
                    &format!("target_prefix = {target:?}"),
                ),
        );
    }
}
impl Drop for Repo {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}
fn findings<'a>(payload: &'a Value, id: &str) -> Vec<&'a Value> {
    payload["data"]["findings"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|f| f["rule_id"] == id)
        .collect()
}

#[test]
fn missing_source_requires_filesystem_absence_with_supported_aliases() {
    let repo = Repo::new();
    repo.write("src/app.ts", "import './existing.js';\nimport './missing.ts';\nimport './asset.svg';\nimport './unindexed.ts';\nimport './extensionless';\nimport './loader.ts?raw';\nimport './ambiguous';\nimport './ghost.ts';\n");
    repo.write("src/existing.ts", "export const existing = 1;");
    repo.write("src/unindexed.ts", "export const ignored = 1;");
    repo.write(".ignore", "src/unindexed.ts\n");
    repo.write("src/ambiguous.ts", "export const typed = 1;");
    repo.write("src/ambiguous.js", "export const plain = 1;");
    repo.write("other/ghost.ts", "export const unrelated = 1;");
    let payload = repo.scan();
    let missing = findings(&payload, "unresolved-local-import");
    let mut specifiers: Vec<_> = missing
        .iter()
        .map(|f| f["evidence"]["specifier"].as_str().unwrap())
        .collect();
    specifiers.sort();
    assert_eq!(specifiers, vec!["./ghost.ts", "./missing.ts"]);
    assert_eq!(payload["data"]["gate"]["status"], "fail");
    assert!(missing.iter().all(|f| f["severity"] == "error"));
}

#[test]
fn dependency_counts_deduplicate_imports_and_ignore_calls() {
    let repo = Repo::new();
    repo.fan_limit(2);
    repo.write("src/app.ts", "import { a } from './a';\nimport { a as again } from './a';\nimport { b } from './b';\nexport function run() { a(); a(); again(); b(); }\n");
    repo.write("src/a.ts", "export function a() {}\n");
    repo.write("src/b.ts", "export function b() {}\n");
    let payload = repo.scan();
    let fan = findings(&payload, "low-fan-in-high-fan-out-file");
    assert_eq!(fan.len(), 1, "{payload}");
    assert_eq!(fan[0]["evidence"]["fan_out"], 2);
    assert_eq!(fan[0]["evidence"]["fan_in"], 0);
    repo.fan_limit(3);
    assert!(findings(&repo.scan(), "low-fan-in-high-fan-out-file").is_empty());
}

#[test]
fn reciprocal_cycles_are_unique_and_exclude_type_only_and_test_edges() {
    let repo = Repo::new();
    repo.write("src/a.ts", "import { b } from './b';\nimport { b as again } from './b';\nexport function a() { b(); again(); }\n");
    repo.write(
        "src/b.ts",
        "import { a } from './a';\nexport function b() { a(); }\n",
    );
    let payload = repo.scan();
    let cycles = findings(&payload, "circular-import");
    assert_eq!(cycles.len(), 1, "{payload}");
    assert_eq!(cycles[0]["evidence"]["from_unit"], "src/a.ts");
    assert_eq!(cycles[0]["evidence"]["to_unit"], "src/b.ts");
    repo.write(
        "src/b.ts",
        "import type { a } from './a';\nexport function b() {}\n",
    );
    assert!(findings(&repo.scan(), "circular-import").is_empty());
    repo.write("tests/a.test.ts", "import '../src/b';\n");
    repo.write("src/b.ts", "import '../tests/a.test';\n");
    assert!(findings(&repo.scan(), "circular-import").is_empty());
}

#[test]
fn declared_boundaries_match_literal_directory_segments() {
    let repo = Repo::new();
    repo.boundary("src/core", "src/data");
    repo.write(
        "src/core/a.ts",
        "import '../data/a';\nimport '../database/a';\n",
    );
    repo.write("src/corex/a.ts", "import '../data/a';\n");
    repo.write("src/data/a.ts", "export const a = 1;\n");
    repo.write("src/database/a.ts", "export const a = 1;\n");
    let payload = repo.scan();
    let violations = findings(&payload, "dependency-boundary");
    assert_eq!(violations.len(), 1, "{payload}");
    assert_eq!(violations[0]["location"]["file"], "src/core/a.ts");
    repo.boundary("src/co%", "src/data");
    assert!(findings(&repo.scan(), "dependency-boundary").is_empty());
    repo.write("src/co%/a.ts", "import '../data/a';\n");
    assert_eq!(findings(&repo.scan(), "dependency-boundary").len(), 1);
}

#[test]
fn unconfigured_boundaries_cannot_silently_pass_explicit_gates() {
    let repo = Repo::new();
    repo.write("src/a.ts", "export const a = 1;\n");
    let (_, list) = repo.command("rules_list", serde_json::json!({}));
    let rule = list["data"]["rules"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["id"] == "dependency-boundary")
        .unwrap();
    assert_eq!(rule["configuration_status"], "requires_configuration");
    let (ok, payload) = repo.command(
        "scan",
        serde_json::json!({"gateRules":["dependency-boundary"],"apply":true}),
    );
    assert!(!ok);
    assert_eq!(payload["data"]["error"]["code"], "invalid_input");
    assert!(
        !repo.root.join("home").exists(),
        "validation precedes index writes"
    );
    repo.boundary("src/core", "");
    let (ok, payload) = repo.command("scan", serde_json::json!({}));
    assert!(!ok);
    assert_eq!(payload["data"]["gate"]["status"], "unknown");
    assert_eq!(payload["data"]["analysis"]["status"], "incomplete");
    repo.boundary("src/core", "src/data");
    let (_, list) = repo.command("rules_list", serde_json::json!({}));
    let rule = list["data"]["rules"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["id"] == "dependency-boundary")
        .unwrap();
    assert_eq!(rule["configuration_status"], "configured");
    let (ok, payload) = repo.command(
        "scan",
        serde_json::json!({"gateRules":["dependency-boundary"]}),
    );
    assert!(ok, "{payload}");
    assert_eq!(payload["data"]["gate"]["status"], "pass");
}

#[test]
fn go_packages_count_once_and_mutual_packages_report_one_cycle() {
    let repo = Repo::new();
    repo.fan_limit(2);
    repo.write("go.mod", "module example.com/policy\n\ngo 1.22\n");
    repo.write(
        "app/main.go",
        "package app\nimport \"example.com/policy/dep\"\nfunc Run() { dep.Work() }\n",
    );
    for n in 0..20 {
        repo.write(
            &format!("dep/d{n:02}.go"),
            &format!("package dep\nfunc Work{n}() {{}}\n"),
        );
    }
    assert!(findings(&repo.scan(), "low-fan-in-high-fan-out-file").is_empty());
    repo.write("other/other.go", "package other\nfunc Work() {}\n");
    repo.write("app/main.go", "package app\nimport \"example.com/policy/dep\"\nimport \"example.com/policy/other\"\nfunc Run() { dep.Work0(); other.Work() }\n");
    let payload = repo.scan();
    let fan = findings(&payload, "low-fan-in-high-fan-out-file");
    assert_eq!(fan.len(), 1, "{payload}");
    assert_eq!(fan[0]["evidence"]["fan_out"], 2);
    repo.write(
        "dep/back.go",
        "package dep\nimport \"example.com/policy/app\"\nfunc Back() { app.Run() }\n",
    );
    repo.write(
        "dep/another.go",
        "package dep\nimport \"example.com/policy/app\"\nfunc Again() { app.Run() }\n",
    );
    let payload = repo.scan();
    assert_eq!(findings(&payload, "circular-import").len(), 1, "{payload}");
    let fan = findings(&payload, "low-fan-in-high-fan-out-file");
    assert_eq!(fan[0]["evidence"]["fan_in"], 2);
    repo.boundary("app", "dep");
    let payload = repo.scan();
    let boundary = findings(&payload, "dependency-boundary");
    assert_eq!(boundary.len(), 1);
    assert_eq!(boundary[0]["evidence"]["to_unit"], "dep");
}

#[cfg(unix)]
#[test]
fn filesystem_errors_make_dependency_gates_incomplete() {
    let repo = Repo::new();
    repo.write("src/app.ts", "import './loop.ts';\n");
    repo.write(".ignore", "src/loop.ts\n");
    std::os::unix::fs::symlink("loop.ts", repo.root.join("src/loop.ts")).unwrap();
    let (ok, payload) = repo.command("scan", serde_json::json!({}));
    assert!(!ok, "{payload}");
    assert_eq!(payload["data"]["gate"]["status"], "unknown", "{payload}");
    assert_eq!(payload["data"]["analysis"]["status"], "incomplete");
    assert!(findings(&payload, "unresolved-local-import").is_empty());
    assert!(
        payload["data"]["diagnostics"]
            .as_array()
            .unwrap()
            .iter()
            .any(|d| d["reason"]
                .as_str()
                .unwrap_or("")
                .contains("dependency certification failed"))
    );
}

#[test]
fn shipped_dependency_budgets_include_exact_boundaries() {
    let repo = Repo::new();
    let mut imports = String::new();
    for n in 0..15 {
        repo.write(
            &format!("src/d{n}.ts"),
            &format!("export const value{n} = {n};\n"),
        );
        if n < 14 {
            imports.push_str(&format!("import './d{n}';\n"));
        }
    }
    repo.write("src/app.ts", &imports);
    assert!(findings(&repo.scan(), "low-fan-in-high-fan-out-file").is_empty());
    imports.push_str("import './d14';\n");
    repo.write("src/app.ts", &imports);
    for n in 0..2 {
        repo.write(&format!("src/caller{n}.ts"), "import './app';\n");
    }
    let payload = repo.scan();
    let fan = findings(&payload, "low-fan-in-high-fan-out-file");
    assert_eq!(fan.len(), 1, "{payload}");
    assert_eq!(fan[0]["evidence"]["fan_out"], 15);
    assert_eq!(fan[0]["evidence"]["fan_in"], 2);
    repo.write("src/caller2.ts", "import './app';\n");
    assert!(findings(&repo.scan(), "low-fan-in-high-fan-out-file").is_empty());
}

#[test]
fn source_relative_import_policies_cover_applicable_languages() {
    for (extension, prefix, target) in [
        ("js", "import", "export const value = 1;"),
        ("ts", "import", "export const value = 1;"),
        ("tsx", "import", "export const value = 1;"),
        ("dart", "import", "const value = 1;"),
        ("sol", "import", "contract Target {}"),
    ] {
        let repo = Repo::new();
        repo.boundary("src/core", "src/data");
        repo.write(
            &format!("src/core/app.{extension}"),
            &format!("{prefix} '../data/value.{extension}';\n{prefix} './missing.{extension}';\n"),
        );
        repo.write(&format!("src/data/value.{extension}"), target);
        let payload = repo.scan();
        assert_eq!(
            findings(&payload, "dependency-boundary").len(),
            1,
            "{extension}: {payload}"
        );
        assert_eq!(
            findings(&payload, "unresolved-local-import").len(),
            1,
            "{extension}: {payload}"
        );
    }
}

#[test]
fn mixed_javascript_typescript_targets_are_supported_without_guessing_ambiguities() {
    let repo = Repo::new();
    repo.boundary("src/core", "src/data");
    repo.write("src/core/app.ts", "import '../data/plain.js';\nimport '../data/ambiguous';\nimport type { T } from './missing-type.ts';\n");
    repo.write("src/data/plain.js", "export const plain = 1;\n");
    repo.write("src/data/ambiguous.ts", "export const typed = 1;\n");
    repo.write("src/data/ambiguous.js", "export const plain = 1;\n");
    let payload = repo.scan();
    assert!(
        findings(&payload, "unresolved-local-import").is_empty(),
        "{payload}"
    );
    let boundary = findings(&payload, "dependency-boundary");
    assert_eq!(boundary.len(), 1, "{payload}");
    assert_eq!(boundary[0]["evidence"]["to_unit"], "src/data/plain.js");
}

#[test]
fn dart_and_solidity_do_not_guess_extensions() {
    for (extension, target) in [("dart", "const value = 1;"), ("sol", "contract Target {}")] {
        let repo = Repo::new();
        repo.boundary("src/core", "src/data");
        repo.write(
            &format!("src/core/app.{extension}"),
            "import '../data/value';\n",
        );
        repo.write(&format!("src/data/value.{extension}"), target);
        let payload = repo.scan();
        assert!(
            findings(&payload, "dependency-boundary").is_empty(),
            "{extension}: {payload}"
        );
        assert!(findings(&payload, "unresolved-local-import").is_empty());
    }
}

#[test]
fn directory_and_extensionless_loader_cases_do_not_become_guessed_facts() {
    let repo = Repo::new();
    repo.boundary("src/core", "src/data");
    repo.write(
        "src/core/app.ts",
        "import '../data/folder.ts';\nimport '../data/exact';\nimport '../data/package';\n",
    );
    repo.write("src/data/folder.ts/index.ts", "export const value = 1;\n");
    repo.write("src/data/exact", "module.exports = 1;\n");
    repo.write("src/data/exact.ts", "export const value = 1;\n");
    repo.write("src/data/package/package.json", "{\"main\":\"other.js\"}");
    repo.write("src/data/package/index.ts", "export const value = 1;\n");
    repo.write("src/data/package/other.js", "export const other = 1;\n");
    let payload = repo.scan();
    assert!(
        findings(&payload, "unresolved-local-import").is_empty(),
        "{payload}"
    );
    assert!(
        findings(&payload, "dependency-boundary").is_empty(),
        "{payload}"
    );
}

#[test]
fn encoded_and_escaped_import_specifiers_are_not_treated_as_literal_paths() {
    let repo = Repo::new();
    repo.boundary("src/core", "src/data");
    repo.write(
        "src/core/app.ts",
        r#"import '../data/percent%20name.ts';
import '../data/escaped\u0020name.ts';
import '../data/trailing.ts ';
"#,
    );
    repo.write("src/data/percent name.ts", "export const value = 1;\n");
    repo.write("src/data/escaped name.ts", "export const value = 1;\n");
    repo.write("src/data/trailing.ts", "export const value = 1;\n");
    let payload = repo.scan();
    assert!(
        findings(&payload, "unresolved-local-import").is_empty(),
        "{payload}"
    );
    assert!(
        findings(&payload, "dependency-boundary").is_empty(),
        "{payload}"
    );
}
