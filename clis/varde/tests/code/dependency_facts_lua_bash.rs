//! Dependency-fact end-to-end cases for Lua and Bash imports.
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
            "varde-dependency-facts-lua_bash-{}-{}-{}",
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

#[test]
fn lua_modules_that_require_each_other_form_a_cycle() {
    let repo = Repo::new();
    repo.write("lua/a.lua", "local b = require(\"b\")\nreturn b\n");
    repo.write("lua/b.lua", "local a = require(\"a\")\nreturn a\n");
    let payload = repo.scan();
    let cycles = findings(&payload, "circular-import");
    assert_eq!(cycles.len(), 1, "{payload}");
    assert_eq!(cycles[0]["evidence"]["from_unit"], "lua/a.lua");
    assert_eq!(cycles[0]["evidence"]["to_unit"], "lua/b.lua");
}

#[test]
fn lua_require_with_no_sibling_candidate_is_missing() {
    let repo = Repo::new();
    repo.write("lua/a/keep.lua", "return {}\n");
    repo.write(
        "lua/a/init.lua",
        "local gone = require(\"a.gone\")\nreturn gone\n",
    );
    let payload = repo.scan();
    let missing = findings(&payload, "unresolved-local-import");
    assert_eq!(missing.len(), 1, "{payload}");
    // The extractor stores the dotted module name with slashes.
    assert_eq!(missing[0]["evidence"]["specifier"], "a/gone");
}

#[test]
fn lua_valid_requires_and_external_names_yield_no_finding() {
    let repo = Repo::new();
    repo.write("lua/a/init.lua", "return require(\"a.b\")\n");
    repo.write("lua/a/b.lua", "return {}\n");
    // `kong/resty/` nests the name of an OpenResty module namespace, but it is
    // not a module root, so `require "resty.upload"` stays external and no
    // `missing` fact may be emitted for it.
    repo.write("kong/resty/keep.lua", "return {}\n");
    repo.write(
        "lua/deps.lua",
        "local json = require(\"json\")\nlocal resty = require(\"resty.core\")\nlocal upload = require(\"resty.upload\")\nreturn json, resty, upload\n",
    );
    assert_none(&repo.scan());
}

#[test]
fn lua_ambiguous_and_dynamic_requires_yield_no_finding() {
    let repo = Repo::new();
    repo.write("lua/a.lua", "return require(\"b\")\n");
    repo.write(
        "lua/dynamic.lua",
        "local n = \"b\"\nreturn require(n), require(\"b\" .. n)\n",
    );
    repo.write("lua/b.lua", "return {}\n");
    repo.write("lua/b/init.lua", "return {}\n");
    assert_none(&repo.scan());
}

#[test]
fn bash_sources_that_include_each_other_form_a_cycle() {
    let repo = Repo::new();
    repo.write("shell/a.sh", "source ./b.sh\n");
    repo.write("shell/b.sh", ". ./a.sh\n");
    let payload = repo.scan();
    let cycles = findings(&payload, "circular-import");
    assert_eq!(cycles.len(), 1, "{payload}");
    assert_eq!(cycles[0]["evidence"]["from_unit"], "shell/a.sh");
    assert_eq!(cycles[0]["evidence"]["to_unit"], "shell/b.sh");
}

#[test]
fn bash_source_with_no_candidate_is_missing() {
    let repo = Repo::new();
    repo.write("shell/a.sh", "source ./gone.sh\n");
    let payload = repo.scan();
    let missing = findings(&payload, "unresolved-local-import");
    assert_eq!(missing.len(), 1, "{payload}");
    assert_eq!(missing[0]["evidence"]["specifier"], "./gone.sh");
}

#[test]
fn bash_valid_source_and_non_literal_forms_yield_no_finding() {
    let repo = Repo::new();
    repo.write("shell/lib.sh", "echo lib\n");
    repo.write(
        "shell/a.sh",
        "source ./lib.sh\n. \"$DIR/other.sh\"\nsource /etc/os-release\nsource other.sh\n",
    );
    assert_none(&repo.scan());
}

#[test]
fn declared_boundary_flags_a_forbidden_lua_require() {
    let repo = Repo::new();
    repo.boundary("lua/core", "lua/data");
    repo.write("lua/core/a.lua", "return require(\"data.b\")\n");
    repo.write("lua/core/c.lua", "return require(\"core.d\")\n");
    repo.write("lua/core/d.lua", "return {}\n");
    repo.write("lua/data/b.lua", "return {}\n");
    let payload = repo.scan();
    let violations = findings(&payload, "dependency-boundary");
    assert_eq!(violations.len(), 1, "{payload}");
    assert_eq!(violations[0]["evidence"]["to_unit"], "lua/data/b.lua");
}

#[test]
fn declared_boundary_flags_a_forbidden_bash_source() {
    let repo = Repo::new();
    repo.boundary("shell/core", "shell/data");
    repo.write("shell/core/a.sh", "source ../data/d.sh\n");
    repo.write("shell/data/d.sh", "echo d\n");
    let payload = repo.scan();
    let violations = findings(&payload, "dependency-boundary");
    assert_eq!(violations.len(), 1, "{payload}");
    assert_eq!(violations[0]["evidence"]["to_unit"], "shell/data/d.sh");
}
