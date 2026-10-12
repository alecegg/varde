//! Dependency-fact end-to-end cases for Java, Kotlin and Scala imports.
//!
//! Harness conventions follow `dependency_policy_gates.rs`: build the fixture
//! index with `varde map build`, then scan the fixture and filter findings by
//! rule id.

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
    fn home(&self) -> PathBuf {
        self.root.with_extension("home")
    }
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "varde-dependency-facts-jvm-{}-{}-{}",
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
        // Production scans read the watcher-owned index. Keep this fixture's
        // index current explicitly after each source edit.
        if command == "scan" && input["apply"] != true {
            let built = Command::new(env!("CARGO_BIN_EXE_varde"))
                .args(["map", "build", "--repo-root", self.root.to_str().unwrap()])
                .env("HOME", self.home())
                .output()
                .unwrap();
            assert!(
                built.status.success(),
                "{}",
                String::from_utf8_lossy(&built.stdout)
            );
        }
        let command_args: &[&str] = match command {
            "scan" => &["scan"],
            "rules_list" => &["scan", "rules", "list"],
            _ => panic!("unsupported scan command: {command}"),
        };
        let output = Command::new(env!("CARGO_BIN_EXE_varde"))
            .args(command_args)
            .args(["--json", &input.to_string()])
            .env("HOME", self.home())
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
    fn boundary(&self, source: &str, target: &str) {
        self.write(
            ".varde-code/rules/boundary.toml",
            &include_str!(
                "../../../code/crates/varde-code/src/rules/builtin/dependency_boundary.toml"
            )
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
        let _ = std::fs::remove_dir_all(self.home());
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

fn assert_none(payload: &Value) {
    for id in ["circular-import", "unresolved-local-import"] {
        assert!(findings(payload, id).is_empty(), "{id}: {payload}");
    }
}

/// A unit declaring `class Name` in `package` with one `import` line per
/// entry, written at `<dir>/<Name>.<extension>`.
fn unit(repo: &Repo, dir: &str, package: &str, imports: &[&str], name: &str, extension: &str) {
    let terminator = if extension == "java" { ";" } else { "" };
    let visibility = if extension == "java" { "public " } else { "" };
    let mut body = format!("package {package}{terminator}\n");
    for import in imports {
        body.push_str(&format!("import {import}{terminator}\n"));
    }
    body.push_str(&format!("\n{visibility}class {name} {{}}\n"));
    repo.write(&format!("{dir}/{name}.{extension}"), &body);
}

#[test]
fn repository_indexes_and_scans_without_dependency_findings() {
    let repo = Repo::new();
    repo.write("src/app.txt", "placeholder\n");
    assert_none(&repo.scan());
}

#[test]
fn java_cycle_between_package_directories_is_reported_once() {
    let repo = Repo::new();
    unit(
        &repo,
        "src/main/java/com/example/alpha",
        "com.example.alpha",
        &["com.example.beta.Beta"],
        "Alpha",
        "java",
    );
    unit(
        &repo,
        "src/main/java/com/example/beta",
        "com.example.beta",
        &["com.example.alpha.Alpha"],
        "Beta",
        "java",
    );
    let payload = repo.scan();
    let cycles = findings(&payload, "circular-import");
    assert_eq!(cycles.len(), 1, "{payload}");
    assert_eq!(
        cycles[0]["evidence"]["from_unit"],
        "src/main/java/com/example/alpha"
    );
    assert_eq!(
        cycles[0]["evidence"]["to_unit"],
        "src/main/java/com/example/beta"
    );
}

#[test]
fn java_missing_import_in_a_repository_package_is_reported() {
    let repo = Repo::new();
    unit(
        &repo,
        "src/main/java/com/example/alpha",
        "com.example.alpha",
        &["com.example.gone.Gone"],
        "Alpha",
        "java",
    );
    unit(
        &repo,
        "src/main/java/com/example/gone",
        "com.example.gone",
        &[],
        "Placeholder",
        "java",
    );
    let payload = repo.scan();
    let missing = findings(&payload, "unresolved-local-import");
    assert_eq!(missing.len(), 1, "{payload}");
    assert_eq!(missing[0]["evidence"]["specifier"], "com/example/gone/Gone");
}

#[test]
fn java_valid_external_and_ambiguous_imports_yield_no_finding() {
    let repo = Repo::new();
    unit(
        &repo,
        "src/main/java/com/example/alpha",
        "com.example.alpha",
        &[
            "java.util.List",
            "org.external.Thing",
            "com.example.beta.Beta",
        ],
        "Alpha",
        "java",
    );
    unit(
        &repo,
        "src/main/java/com/example/beta",
        "com.example.beta",
        &[],
        "Beta",
        "java",
    );
    unit(
        &repo,
        "src/main/java/com/example/dup",
        "com.example.dup",
        &["com.example.beta.Beta"],
        "Dup",
        "java",
    );
    unit(
        &repo,
        "src/main/java/com/example/dup2",
        "com.example.dup",
        &[],
        "Dup",
        "java",
    );
    assert_none(&repo.scan());
}

#[test]
fn java_static_wildcard_and_commented_imports_yield_no_finding() {
    let repo = Repo::new();
    repo.write(
        "src/main/java/com/example/alpha/Alpha.java",
        "package com.example.alpha;\n\
         import static com.example.beta.Beta.VALUE;\n\
         import com.example.beta.*;\n\
         // import com.example.gone.Gone;\n\
         /* import com.example.gone.Other; */\n\
         public class Alpha {}\n",
    );
    unit(
        &repo,
        "src/main/java/com/example/beta",
        "com.example.beta",
        &["com.example.alpha.Alpha"],
        "Beta",
        "java",
    );
    unit(
        &repo,
        "src/main/java/com/example/gone",
        "com.example.gone",
        &[],
        "Placeholder",
        "java",
    );
    assert_none(&repo.scan());
}

#[test]
fn java_dependency_boundary_uses_package_directory_units() {
    let repo = Repo::new();
    unit(
        &repo,
        "src/main/java/com/example/alpha",
        "com.example.alpha",
        &["com.example.beta.Beta"],
        "Alpha",
        "java",
    );
    unit(
        &repo,
        "src/main/java/com/example/beta",
        "com.example.beta",
        &[],
        "Beta",
        "java",
    );
    repo.boundary(
        "src/main/java/com/example/alpha",
        "src/main/java/com/example/beta",
    );
    let payload = repo.scan();
    assert_eq!(
        findings(&payload, "dependency-boundary").len(),
        1,
        "{payload}"
    );
    repo.boundary(
        "src/main/java/com/example/beta",
        "src/main/java/com/example/alpha",
    );
    assert!(findings(&repo.scan(), "dependency-boundary").is_empty());
}

#[test]
fn java_scala_module_class_import_participates_in_a_cycle() {
    let repo = Repo::new();
    repo.write(
        "src/main/scala/com/example/beta/Registry.scala",
        "package com.example.beta\n\nimport com.example.alpha.Alpha\n\nobject Registry\n",
    );
    repo.write(
        "src/main/java/com/example/alpha/Alpha.java",
        "package com.example.alpha;\n\nimport com.example.beta.Registry$;\n\npublic class Alpha {}\n",
    );
    let payload = repo.scan();
    assert_eq!(findings(&payload, "circular-import").len(), 1, "{payload}");
}

#[test]
fn missing_import_across_source_roots_yields_no_finding() {
    let repo = Repo::new();
    unit(
        &repo,
        "src/main/java/com/example/alpha",
        "com.example.alpha",
        &["com.example.gone.Gone"],
        "Alpha",
        "java",
    );
    // The package is declared only in another source root, so the type may
    // come from a sibling module or an external library.
    repo.write(
        "src/main/kotlin/com/example/gone/Placeholder.kt",
        "package com.example.gone\n\nclass Placeholder\n",
    );
    assert_none(&repo.scan());
}

#[test]
fn kotlin_cycle_between_package_directories_is_reported_once() {
    let repo = Repo::new();
    unit(
        &repo,
        "src/main/kotlin/com/example/alpha",
        "com.example.alpha",
        &["com.example.beta.Beta"],
        "Alpha",
        "kt",
    );
    unit(
        &repo,
        "src/main/kotlin/com/example/beta",
        "com.example.beta",
        &["com.example.alpha.Alpha"],
        "Beta",
        "kt",
    );
    let payload = repo.scan();
    let cycles = findings(&payload, "circular-import");
    assert_eq!(cycles.len(), 1, "{payload}");
    assert_eq!(
        cycles[0]["evidence"]["from_unit"],
        "src/main/kotlin/com/example/alpha"
    );
    assert_eq!(
        cycles[0]["evidence"]["to_unit"],
        "src/main/kotlin/com/example/beta"
    );
}

#[test]
fn kotlin_missing_import_in_a_repository_package_is_reported() {
    let repo = Repo::new();
    unit(
        &repo,
        "src/main/kotlin/com/example/alpha",
        "com.example.alpha",
        &["com.example.gone.Gone"],
        "Alpha",
        "kt",
    );
    unit(
        &repo,
        "src/main/kotlin/com/example/gone",
        "com.example.gone",
        &[],
        "Placeholder",
        "kt",
    );
    let payload = repo.scan();
    let missing = findings(&payload, "unresolved-local-import");
    assert_eq!(missing.len(), 1, "{payload}");
    assert_eq!(missing[0]["evidence"]["specifier"], "com/example/gone/Gone");
}

#[test]
fn kotlin_valid_alias_external_and_ambiguous_imports_yield_no_finding() {
    let repo = Repo::new();
    unit(
        &repo,
        "src/main/kotlin/com/example/alpha",
        "com.example.alpha",
        &["kotlin.collections.List", "com.example.beta.Beta as B"],
        "Alpha",
        "kt",
    );
    unit(
        &repo,
        "src/main/kotlin/com/example/beta",
        "com.example.beta",
        &[],
        "Beta",
        "kt",
    );
    unit(
        &repo,
        "src/main/kotlin/com/example/dup",
        "com.example.dup",
        &["com.example.beta.Beta"],
        "Dup",
        "kt",
    );
    unit(
        &repo,
        "src/main/kotlin/com/example/dup2",
        "com.example.dup",
        &[],
        "Dup",
        "kt",
    );
    assert_none(&repo.scan());
}

#[test]
fn kotlin_wildcard_and_commented_imports_yield_no_finding() {
    let repo = Repo::new();
    repo.write(
        "src/main/kotlin/com/example/alpha/Alpha.kt",
        "package com.example.alpha\n\
         import com.example.beta.*\n\
         // import com.example.gone.Gone\n\
         /* import com.example.gone.Other */\n\
         class Alpha\n",
    );
    unit(
        &repo,
        "src/main/kotlin/com/example/beta",
        "com.example.beta",
        &["com.example.alpha.Alpha"],
        "Beta",
        "kt",
    );
    unit(
        &repo,
        "src/main/kotlin/com/example/gone",
        "com.example.gone",
        &[],
        "Placeholder",
        "kt",
    );
    assert_none(&repo.scan());
}

#[test]
fn kotlin_dependency_boundary_uses_package_directory_units() {
    let repo = Repo::new();
    unit(
        &repo,
        "src/main/kotlin/com/example/alpha",
        "com.example.alpha",
        &["com.example.beta.Beta"],
        "Alpha",
        "kt",
    );
    unit(
        &repo,
        "src/main/kotlin/com/example/beta",
        "com.example.beta",
        &[],
        "Beta",
        "kt",
    );
    repo.boundary(
        "src/main/kotlin/com/example/alpha",
        "src/main/kotlin/com/example/beta",
    );
    let payload = repo.scan();
    assert_eq!(
        findings(&payload, "dependency-boundary").len(),
        1,
        "{payload}"
    );
    repo.boundary(
        "src/main/kotlin/com/example/beta",
        "src/main/kotlin/com/example/alpha",
    );
    assert!(findings(&repo.scan(), "dependency-boundary").is_empty());
}

#[test]
fn scala_cycle_between_package_directories_is_reported_once() {
    let repo = Repo::new();
    unit(
        &repo,
        "src/main/scala/com/example/alpha",
        "com.example.alpha",
        &["com.example.beta.Beta"],
        "Alpha",
        "scala",
    );
    unit(
        &repo,
        "src/main/scala/com/example/beta",
        "com.example.beta",
        &["com.example.alpha.Alpha"],
        "Beta",
        "scala",
    );
    let payload = repo.scan();
    let cycles = findings(&payload, "circular-import");
    assert_eq!(cycles.len(), 1, "{payload}");
    assert_eq!(
        cycles[0]["evidence"]["from_unit"],
        "src/main/scala/com/example/alpha"
    );
    assert_eq!(
        cycles[0]["evidence"]["to_unit"],
        "src/main/scala/com/example/beta"
    );
}

#[test]
fn scala_missing_import_in_a_repository_package_is_reported() {
    let repo = Repo::new();
    unit(
        &repo,
        "src/main/scala/com/example/alpha",
        "com.example.alpha",
        &["com.example.gone.Gone"],
        "Alpha",
        "scala",
    );
    unit(
        &repo,
        "src/main/scala/com/example/gone",
        "com.example.gone",
        &[],
        "Placeholder",
        "scala",
    );
    let payload = repo.scan();
    let missing = findings(&payload, "unresolved-local-import");
    assert_eq!(missing.len(), 1, "{payload}");
    assert_eq!(missing[0]["evidence"]["specifier"], "com/example/gone/Gone");
}

#[test]
fn scala_valid_external_and_ambiguous_imports_yield_no_finding() {
    let repo = Repo::new();
    unit(
        &repo,
        "src/main/scala/com/example/alpha",
        "com.example.alpha",
        &["scala.collection.immutable.List", "com.example.beta.Beta"],
        "Alpha",
        "scala",
    );
    unit(
        &repo,
        "src/main/scala/com/example/beta",
        "com.example.beta",
        &[],
        "Beta",
        "scala",
    );
    unit(
        &repo,
        "src/main/scala/com/example/dup",
        "com.example.dup",
        &["com.example.beta.Beta"],
        "Dup",
        "scala",
    );
    unit(
        &repo,
        "src/main/scala/com/example/dup2",
        "com.example.dup",
        &[],
        "Dup",
        "scala",
    );
    assert_none(&repo.scan());
}

#[test]
fn scala_wildcard_selector_and_commented_imports_yield_no_finding() {
    let repo = Repo::new();
    repo.write(
        "src/main/scala/com/example/alpha/Alpha.scala",
        "package com.example.alpha\n\
         import com.example.beta._\n\
         import com.example.beta.{Beta}\n\
         // import com.example.gone.Gone\n\
         /* import com.example.gone.Other */\n\
         class Alpha\n",
    );
    unit(
        &repo,
        "src/main/scala/com/example/beta",
        "com.example.beta",
        &["com.example.alpha.Alpha"],
        "Beta",
        "scala",
    );
    unit(
        &repo,
        "src/main/scala/com/example/gone",
        "com.example.gone",
        &[],
        "Placeholder",
        "scala",
    );
    assert_none(&repo.scan());
}

#[test]
fn scala_dependency_boundary_uses_package_directory_units() {
    let repo = Repo::new();
    unit(
        &repo,
        "src/main/scala/com/example/alpha",
        "com.example.alpha",
        &["com.example.beta.Beta"],
        "Alpha",
        "scala",
    );
    unit(
        &repo,
        "src/main/scala/com/example/beta",
        "com.example.beta",
        &[],
        "Beta",
        "scala",
    );
    repo.boundary(
        "src/main/scala/com/example/alpha",
        "src/main/scala/com/example/beta",
    );
    let payload = repo.scan();
    assert_eq!(
        findings(&payload, "dependency-boundary").len(),
        1,
        "{payload}"
    );
    repo.boundary(
        "src/main/scala/com/example/beta",
        "src/main/scala/com/example/alpha",
    );
    assert!(findings(&repo.scan(), "dependency-boundary").is_empty());
}
