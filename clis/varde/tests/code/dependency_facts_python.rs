//! Dependency-fact end-to-end cases for python imports; filled by the owning task.
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
            "varde-dependency-facts-python-{}-{}-{}",
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
fn relative_imports_that_import_each_other_form_a_cycle() {
    let repo = Repo::new();
    repo.write("pkg/__init__.py", "");
    repo.write("pkg/a.py", "from . import b\n");
    repo.write("pkg/b.py", "from . import a\n");
    let payload = repo.scan();
    let cycles = findings(&payload, "circular-import");
    assert_eq!(cycles.len(), 1, "{payload}");
    assert_eq!(cycles[0]["evidence"]["from_unit"], "pkg/a.py");
    assert_eq!(cycles[0]["evidence"]["to_unit"], "pkg/b.py");
}

#[test]
fn relative_import_with_no_candidate_is_missing() {
    let repo = Repo::new();
    repo.write("pkg/__init__.py", "");
    repo.write("pkg/a.py", "from .gone import thing\n");
    let payload = repo.scan();
    let missing = findings(&payload, "unresolved-local-import");
    assert_eq!(missing.len(), 1, "{payload}");
    assert_eq!(missing[0]["evidence"]["specifier"], "./gone");
}

#[test]
fn valid_relative_and_absolute_imports_yield_no_finding() {
    let repo = Repo::new();
    repo.write("pkg/__init__.py", "");
    repo.write("pkg/sub/__init__.py", "");
    repo.write("pkg/sub/c.py", "value = 1\n");
    repo.write("pkg/b.py", "value = 2\n");
    repo.write(
        "pkg/a.py",
        "from . import b\nfrom .sub import c\nfrom pkg.sub import c as c2\n",
    );
    assert_none(&repo.scan());
}

#[test]
fn guarded_and_ambiguous_imports_yield_no_finding() {
    let repo = Repo::new();
    repo.write("pkg/__init__.py", "");
    repo.write("nspkg/mod.py", "from . import other\n");
    repo.write(
        "pkg/a.py",
        "try:\n    from .gone import x\nexcept ImportError:\n    pass\n\
         try:\n    from .other_gone import y\nexcept ModuleNotFoundError:\n    pass\n\
         from . import attrname\n\
         try:\n    from .required import z\nexcept ValueError:\n    pass\n",
    );
    let payload = repo.scan();
    let missing = findings(&payload, "unresolved-local-import");
    // `from . import attrname` may be an `__init__.py` attribute, so it is not
    // missing; the ValueError handler does not guard a runtime import.
    assert_eq!(missing.len(), 1, "{payload}");
    assert_eq!(missing[0]["evidence"]["specifier"], "./required");
}

#[test]
fn ambiguous_module_with_both_candidates_yields_no_finding() {
    let repo = Repo::new();
    repo.write("pkg/__init__.py", "");
    repo.write("pkg/dup.py", "value = 1\n");
    repo.write("pkg/dup/__init__.py", "");
    repo.write("pkg/a.py", "from .dup import value\n");
    assert_none(&repo.scan());
}

#[test]
fn nested_package_shadowing_a_standard_library_name_yields_no_finding() {
    // `email` is the standard library package, not `plugins/platforms/email`;
    // the nested repository directory is not importable under that top-level
    // name, so the `from email import ...` edges must not certify and must not
    // close the relative-import cycle inside the plugin.
    let repo = Repo::new();
    repo.write(
        "plugins/platforms/email/__init__.py",
        "from .adapter import register\n",
    );
    repo.write(
        "plugins/platforms/email/adapter.py",
        "from email.mime.text import MIMEText\nfrom email import encoders\n",
    );
    assert_none(&repo.scan());
}

#[test]
fn declared_boundary_flags_a_forbidden_import() {
    let repo = Repo::new();
    repo.write("pkg/core/__init__.py", "");
    repo.write("pkg/data/__init__.py", "");
    repo.write("pkg/data/d.py", "value = 1\n");
    repo.write("pkg/other/__init__.py", "");
    repo.write("pkg/other/o.py", "value = 2\n");
    repo.boundary("pkg/core", "pkg/data");
    repo.write(
        "pkg/core/a.py",
        "from ..data.d import value\nfrom ..other.o import value as other\n",
    );
    let payload = repo.scan();
    let violations = findings(&payload, "dependency-boundary");
    assert_eq!(violations.len(), 1, "{payload}");
    assert_eq!(violations[0]["evidence"]["to_unit"], "pkg/data/d.py");
}
