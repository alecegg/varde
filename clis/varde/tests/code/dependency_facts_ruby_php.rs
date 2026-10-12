//! Dependency-fact end-to-end cases for Ruby `require_relative` and PHP
//! `require`/`include` imports.
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
            "varde-dependency-facts-ruby_php-{}-{}-{}",
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

#[test]
fn repository_indexes_and_scans_without_dependency_findings() {
    let repo = Repo::new();
    repo.write("src/app.txt", "placeholder\n");
    assert_none(&repo.scan());
}

// ---- Ruby ----

#[test]
fn ruby_require_relative_cycle_is_reported_once() {
    let repo = Repo::new();
    repo.write("lib/a.rb", "require_relative 'b'\n");
    repo.write("lib/b.rb", "require_relative 'a'\n");
    let payload = repo.scan();
    let cycles = findings(&payload, "circular-import");
    assert_eq!(cycles.len(), 1, "{payload}");
    assert_eq!(cycles[0]["evidence"]["from_unit"], "lib/a.rb");
    assert_eq!(cycles[0]["evidence"]["to_unit"], "lib/b.rb");
}

#[test]
fn ruby_require_relative_with_no_candidate_is_missing() {
    let repo = Repo::new();
    repo.write("lib/a.rb", "require_relative 'gone'\n");
    let payload = repo.scan();
    let missing = findings(&payload, "unresolved-local-import");
    assert_eq!(missing.len(), 1, "{payload}");
    assert_eq!(missing[0]["evidence"]["specifier"], "gone");
}

#[test]
fn ruby_valid_require_relative_yields_no_finding() {
    let repo = Repo::new();
    repo.write("lib/a.rb", "require_relative 'util/util'\n");
    repo.write("lib/util/util.rb", "module Util\nend\n");
    assert_none(&repo.scan());
}

#[test]
fn ruby_guarded_and_dynamic_require_relative_yield_no_finding() {
    let repo = Repo::new();
    repo.write(
        "lib/a.rb",
        "begin\n  require_relative 'gone'\nrescue LoadError\n  nil\nend\n\
         require_relative \"#{dir}/gone_too\"\n",
    );
    assert_none(&repo.scan());
}

#[test]
fn ruby_dependency_boundary_flags_a_forbidden_require() {
    let repo = Repo::new();
    repo.boundary("lib/core", "lib/data");
    repo.write("lib/core/a.rb", "require_relative '../data/d'\n");
    repo.write("lib/data/d.rb", "module D\nend\n");
    let payload = repo.scan();
    let violations = findings(&payload, "dependency-boundary");
    assert_eq!(violations.len(), 1, "{payload}");
    assert_eq!(violations[0]["evidence"]["to_unit"], "lib/data/d.rb");
}

// ---- PHP ----

#[test]
fn php_require_cycle_is_reported_once() {
    let repo = Repo::new();
    repo.write("lib/a.php", "<?php\nrequire_once 'b.php';\n");
    repo.write("lib/b.php", "<?php\nrequire 'a.php';\n");
    let payload = repo.scan();
    let cycles = findings(&payload, "circular-import");
    assert_eq!(cycles.len(), 1, "{payload}");
    assert_eq!(cycles[0]["evidence"]["from_unit"], "lib/a.php");
    assert_eq!(cycles[0]["evidence"]["to_unit"], "lib/b.php");
}

#[test]
fn php_explicit_relative_require_with_no_candidate_is_missing() {
    let repo = Repo::new();
    repo.write("lib/a.php", "<?php\nrequire './gone.php';\n");
    let payload = repo.scan();
    let missing = findings(&payload, "unresolved-local-import");
    assert_eq!(missing.len(), 1, "{payload}");
    assert_eq!(missing[0]["evidence"]["specifier"], "./gone.php");
}

#[test]
fn php_valid_require_yields_no_finding() {
    let repo = Repo::new();
    repo.write("lib/a.php", "<?php\nrequire 'util/util.php';\n");
    repo.write("lib/util/util.php", "<?php\nfunction util() {}\n");
    assert_none(&repo.scan());
}

#[test]
fn php_bare_and_concat_requires_yield_no_finding() {
    let repo = Repo::new();
    repo.write(
        "lib/a.php",
        "<?php\nrequire 'gone.php';\ninclude __DIR__ . '/also_gone.php';\n",
    );
    assert_none(&repo.scan());
}

#[test]
fn php_dependency_boundary_flags_a_forbidden_require() {
    let repo = Repo::new();
    repo.boundary("lib/core", "lib/data");
    repo.write("lib/core/a.php", "<?php\nrequire_once '../data/d.php';\n");
    repo.write("lib/data/d.php", "<?php\nfunction d() {}\n");
    let payload = repo.scan();
    let violations = findings(&payload, "dependency-boundary");
    assert_eq!(violations.len(), 1, "{payload}");
    assert_eq!(violations[0]["evidence"]["to_unit"], "lib/data/d.php");
}
