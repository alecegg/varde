//! Dependency-fact end-to-end cases for C and C++ quoted includes.
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
            "varde-dependency-facts-c_cpp-{}-{}-{}",
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
fn guarded_headers_that_include_each_other_form_a_cycle() {
    let repo = Repo::new();
    repo.write(
        "src/a.h",
        "#ifndef A_H\n#define A_H\n#include \"b.h\"\n#endif\n",
    );
    repo.write(
        "src/b.h",
        "#ifndef B_H\n#define B_H\n#include \"a.h\"\n#endif\n",
    );
    let payload = repo.scan();
    let cycles = findings(&payload, "circular-import");
    assert_eq!(cycles.len(), 1, "{payload}");
    assert_eq!(cycles[0]["evidence"]["from_unit"], "src/a.h");
    assert_eq!(cycles[0]["evidence"]["to_unit"], "src/b.h");
}

#[test]
fn explicit_relative_include_with_no_candidate_is_missing() {
    let repo = Repo::new();
    repo.write(
        "src/main.c",
        "#include \"../gone.h\"\n#include \"./gone-here.h\"\n#include \"bare.h\"\nint main(void) { return 0; }\n",
    );
    let payload = repo.scan();
    let missing = findings(&payload, "unresolved-local-import");
    assert_eq!(missing.len(), 2, "{payload}");
    let specs: Vec<&str> = missing
        .iter()
        .map(|finding| finding["evidence"]["specifier"].as_str().unwrap())
        .collect();
    assert_eq!(specs, ["../gone.h", "./gone-here.h"]);
}

#[test]
fn existing_directory_with_absent_generated_header_is_not_missing() {
    let repo = Repo::new();
    repo.write("src/flutter/.gitkeep", "");
    repo.write(
        "src/main.cc",
        "#include \"flutter/generated_plugin_registrant.h\"\nint main() { return 0; }\n",
    );
    assert_none(&repo.scan());
}

#[test]
fn valid_includes_yield_no_finding() {
    let repo = Repo::new();
    repo.write("src/util.h", "int util(void);\n");
    repo.write("src/inc/deep.h", "int deep(void);\n");
    repo.write(
        "src/main.c",
        "#include \"util.h\"\n#include \"inc/deep.h\"\n#include \"../src/util.h\"\nint main(void) { return util(); }\n",
    );
    repo.write(
        "src/util.c",
        "#include \"util.h\"\nint util(void) { return 0; }\n",
    );
    assert_none(&repo.scan());
}

#[test]
fn guarded_angle_and_ambiguous_includes_yield_no_finding() {
    let repo = Repo::new();
    repo.write("lib/x/shared.h", "int x(void);\n");
    repo.write("lib/y/shared.h", "int y(void);\n");
    repo.write("config.h.in", "#define HAVE_X @HAVE_X@\n");
    repo.write(
        "src/main.c",
        "#ifdef HAVE_GONE\n#include \"gone.h\"\n#endif\n\
         #include <gone2.h>\n\
         #include \"shared.h\"\n\
         #include \"config.h\"\n\
         // #include \"gone3.h\"\n\
         /* #include \"gone4.h\" */\n\
         int main(void) { return 0; }\n",
    );
    assert_none(&repo.scan());
}

#[test]
fn conditional_include_does_not_close_a_cycle() {
    let repo = Repo::new();
    repo.write("src/a.h", "#include \"b.h\"\n");
    repo.write("src/b.h", "#ifdef LATER\n#include \"a.h\"\n#endif\n");
    assert_none(&repo.scan());
}

#[test]
fn declared_boundary_flags_a_forbidden_include() {
    let repo = Repo::new();
    repo.boundary("src/core", "src/data");
    repo.write(
        "src/core/a.c",
        "#include \"../data/d.h\"\n#include \"../other/o.h\"\n",
    );
    repo.write("src/data/d.h", "int d(void);\n");
    repo.write("src/other/o.h", "int o(void);\n");
    let payload = repo.scan();
    let violations = findings(&payload, "dependency-boundary");
    assert_eq!(violations.len(), 1, "{payload}");
    assert_eq!(violations[0]["evidence"]["to_unit"], "src/data/d.h");
}
