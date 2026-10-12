//! Dependency-fact end-to-end cases for rust imports.
//!
//! Harness conventions follow `dependency_policy_gates.rs`: build the fixture
//! index with `varde map build`, then scan the fixture and filter findings by
//! rule id. Rust units are Cargo packages, so the cycle and boundary cases use
//! two crates with a path dependency.

use serde_json::Value;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
static NEXT_REPO: AtomicUsize = AtomicUsize::new(0);

/// A manifest for `name`, optionally depending on `dependency` by path.
fn manifest(name: &str, dependency: Option<&str>) -> String {
    match dependency {
        Some(dependency) => format!(
            "[package]\nname = \"{name}\"\nversion = \"0.1.0\"\nedition = \"2021\"\n\n[dependencies]\n{dependency} = {{ path = \"../{dependency}\" }}\n"
        ),
        None => format!("[package]\nname = \"{name}\"\nversion = \"0.1.0\"\nedition = \"2021\"\n"),
    }
}

struct Repo {
    root: PathBuf,
}
impl Repo {
    fn home(&self) -> PathBuf {
        self.root.with_extension("home")
    }
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "varde-dependency-facts-rust-{}-{}-{}",
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
    /// Scan the persisted index without rebuilding it, as a production scan
    /// does against a watcher-owned index. A `scan` earlier in the test leaves
    /// the index current, so an edit made after it is invisible to the index
    /// while the fact builders still read the file from disk.
    fn scan_stale(&self) -> Value {
        let input = serde_json::json!({ "repoRoot": self.root });
        let output = Command::new(env!("CARGO_BIN_EXE_varde"))
            .args(["scan", "--json", &input.to_string()])
            .env("HOME", self.home())
            .env("VARDE_USER_RULES_DIR", self.root.join("empty-user-rules"))
            .output()
            .unwrap();
        serde_json::from_slice(&output.stdout).unwrap_or_else(|_| {
            panic!(
                "{}\n{}",
                String::from_utf8_lossy(&output.stdout),
                String::from_utf8_lossy(&output.stderr)
            )
        })
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

/// Two crates whose path dependencies point at each other.
fn linked_crates(repo: &Repo) {
    repo.write("alpha/Cargo.toml", &manifest("alpha", Some("beta")));
    repo.write("beta/Cargo.toml", &manifest("beta", Some("alpha")));
}

#[test]
fn repository_indexes_and_scans_without_dependency_findings() {
    let repo = Repo::new();
    repo.write("src/app.txt", "placeholder\n");
    assert_none(&repo.scan());
}

#[test]
fn crates_that_use_each_other_form_a_cycle() {
    let repo = Repo::new();
    linked_crates(&repo);
    repo.write("alpha/src/lib.rs", "use beta::Thing;\npub struct Alpha;\n");
    repo.write("beta/src/lib.rs", "use alpha::Alpha;\npub struct Thing;\n");
    let payload = repo.scan();
    let cycles = findings(&payload, "circular-import");
    assert_eq!(cycles.len(), 1, "{payload}");
    assert_eq!(cycles[0]["evidence"]["from_unit"], "alpha/src/lib.rs");
    assert_eq!(cycles[0]["evidence"]["to_unit"], "beta/src/lib.rs");
}

#[test]
fn rust_mod_with_no_candidate_file_is_missing() {
    let repo = Repo::new();
    repo.write("alpha/Cargo.toml", &manifest("alpha", None));
    repo.write("alpha/src/lib.rs", "mod keep;\nmod gone;\n");
    repo.write("alpha/src/keep.rs", "pub struct Keep;\n");
    let payload = repo.scan();
    let missing = findings(&payload, "unresolved-local-import");
    assert_eq!(missing.len(), 1, "{payload}");
    assert_eq!(missing[0]["evidence"]["specifier"], "mod gone");
}

#[test]
fn rust_valid_cross_crate_import_and_external_crate_yield_no_finding() {
    let repo = Repo::new();
    repo.write("alpha/Cargo.toml", &manifest("alpha", Some("beta")));
    repo.write(
        "alpha/src/lib.rs",
        "use beta::Thing;\nuse serde::Serialize;\npub struct Alpha;\n",
    );
    repo.write("beta/Cargo.toml", &manifest("beta", None));
    repo.write("beta/src/lib.rs", "pub struct Thing;\n");
    assert_none(&repo.scan());
}

#[test]
fn rust_intra_crate_module_uses_are_not_cross_crate_edges() {
    let repo = Repo::new();
    repo.write("alpha/Cargo.toml", &manifest("alpha", None));
    repo.write("alpha/src/lib.rs", "mod a;\nmod b;\n");
    repo.write("alpha/src/a.rs", "use crate::b::B;\npub struct A;\n");
    repo.write("alpha/src/b.rs", "use crate::a::A;\npub struct B;\n");
    assert_none(&repo.scan());
}

#[test]
fn rust_cfg_guarded_and_path_attributed_modules_yield_no_finding() {
    let repo = Repo::new();
    repo.write("alpha/Cargo.toml", &manifest("alpha", None));
    repo.write(
        "alpha/src/lib.rs",
        "#[cfg(test)]\nmod tests;\n\n#[cfg(feature = \"extra\")]\nmod optional;\n\n#[path = \"custom/renamed.rs\"]\nmod renamed;\n",
    );
    repo.write("alpha/src/tests.rs", "#[test]\nfn it_works() {}\n");
    repo.write("alpha/src/custom/renamed.rs", "pub struct Renamed;\n");
    assert_none(&repo.scan());
}

#[test]
fn rust_nested_module_with_path_attribute_yields_no_finding() {
    let repo = Repo::new();
    repo.write("alpha/Cargo.toml", &manifest("alpha", None));
    repo.write(
        "alpha/src/lib.rs",
        "mod outer {\n    #[path = \"x.rs\"]\n    mod inner;\n}\n",
    );
    repo.write("alpha/src/outer/x.rs", "pub struct Inner;\n");
    assert_none(&repo.scan());
}

#[test]
fn rust_non_utf8_source_file_does_not_fail_dependency_rules() {
    let repo = Repo::new();
    repo.write("alpha/Cargo.toml", &manifest("alpha", None));
    repo.write("alpha/src/lib.rs", "mod keep;\nmod gone;\n");
    let keep = "use crate::other::Thing;\npub struct Keep;\n";
    repo.write("alpha/src/keep.rs", keep);
    // Index `keep.rs` and its import, then replace its bytes with an invalid
    // UTF-8 sequence of the same length and restore the mtime, so the index
    // stays fresh while the file no longer reads as UTF-8.
    let (_, indexed) = repo.command("scan", serde_json::json!({}));
    assert!(
        indexed["data"]["diagnostics"]
            .as_array()
            .unwrap()
            .is_empty(),
        "{indexed}"
    );
    let keep_path = repo.root.join("alpha/src/keep.rs");
    let modified = std::fs::metadata(&keep_path).unwrap().modified().unwrap();
    let mut bytes = keep.as_bytes().to_vec();
    *bytes.last_mut().unwrap() = 0xff;
    std::fs::write(&keep_path, &bytes).unwrap();
    std::fs::File::options()
        .write(true)
        .open(&keep_path)
        .unwrap()
        .set_times(std::fs::FileTimes::new().set_modified(modified))
        .unwrap();
    let payload = repo.scan_stale();
    assert_eq!(payload["ok"], true, "{payload}");
    assert!(
        payload["data"]["diagnostics"]
            .as_array()
            .unwrap()
            .is_empty(),
        "{payload}"
    );
    let missing = findings(&payload, "unresolved-local-import");
    assert_eq!(missing.len(), 1, "{payload}");
    assert_eq!(missing[0]["evidence"]["specifier"], "mod gone");
}

#[test]
fn declared_boundary_flags_a_forbidden_cross_crate_use() {
    let repo = Repo::new();
    repo.boundary("alpha/src", "beta/src");
    repo.write("alpha/Cargo.toml", &manifest("alpha", Some("beta")));
    repo.write("alpha/src/lib.rs", "use beta::Thing;\npub struct Alpha;\n");
    repo.write("beta/Cargo.toml", &manifest("beta", None));
    repo.write("beta/src/lib.rs", "pub struct Thing;\n");
    let payload = repo.scan();
    let violations = findings(&payload, "dependency-boundary");
    assert_eq!(violations.len(), 1, "{payload}");
    assert_eq!(violations[0]["evidence"]["from_unit"], "alpha/src/lib.rs");
    assert_eq!(violations[0]["evidence"]["to_unit"], "beta/src/lib.rs");
}
