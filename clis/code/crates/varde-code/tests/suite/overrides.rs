use crate::ENV_LOCK;
use std::ffi::{OsStr, OsString};
use std::path::PathBuf;
use varde_code::rules::{RuleKind, Severity, load_rules};

struct EnvGuard(Vec<(&'static str, Option<OsString>)>);

impl EnvGuard {
    fn new() -> Self {
        Self(Vec::new())
    }

    fn set(&mut self, key: &'static str, value: impl AsRef<OsStr>) {
        if !self.0.iter().any(|(saved_key, _)| *saved_key == key) {
            self.0.push((key, std::env::var_os(key)));
        }
        unsafe { std::env::set_var(key, value) };
    }
}

impl Drop for EnvGuard {
    fn drop(&mut self) {
        for (key, value) in self.0.drain(..) {
            if let Some(value) = value {
                unsafe { std::env::set_var(key, value) };
            } else {
                unsafe { std::env::remove_var(key) };
            }
        }
    }
}

fn tempdir(label: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "varde-rule-overrides-{label}-{}",
        std::process::id()
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("temp dir creates");
    dir
}

fn write(path: &std::path::Path, contents: &str) {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).expect("parent dir creates");
    }
    std::fs::write(path, contents).expect("fixture writes");
}

#[test]
fn overrides_apply_after_rule_loading_with_repo_precedence_and_off() {
    let _env_lock = ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let repo = tempdir("repo");
    let user_file = tempdir("user").join("overrides.toml");
    let mut env = EnvGuard::new();
    env.set("VARDE_CODE_USER_OVERRIDES_FILE", &user_file);

    write(
        &repo.join(".varde-code/rules/seeded.toml"),
        r#"
[[rule]]
id = "file-complexity-hotspot"
kind = "pattern"
severity = "warning"
message = "seeded rule definition"
pattern = "foo()"
"#,
    );
    write(
        &user_file,
        r#"
[rules.file-complexity-hotspot]
severity = "info"

[rules.eval-usage]
severity = "warning"

[rules.function-complexity-gate]
severity = "info"

[rules.removed-rule]
severity = "off"
"#,
    );
    write(
        &repo.join(".varde-code/overrides.toml"),
        r#"
[rules.file-complexity-hotspot]
severity = "error"

[rules.eval-usage]
severity = "off"
"#,
    );

    let (rules, diagnostics) = load_rules(&repo);
    let seeded = rules
        .iter()
        .find(|rule| rule.id == "file-complexity-hotspot")
        .expect("seeded rule remains active");
    assert_eq!(seeded.kind, RuleKind::Pattern);
    assert_eq!(seeded.message, "seeded rule definition");
    assert_eq!(seeded.severity, Severity::Error, "repo override wins");

    let user_overridden = rules
        .iter()
        .find(|rule| rule.id == "function-complexity-gate")
        .expect("user-overridden rule remains active");
    assert_eq!(user_overridden.severity, Severity::Info);
    assert!(
        rules.iter().all(|rule| rule.id != "eval-usage"),
        "repo off override removes the active rule"
    );
    assert!(
        !rules.iter().any(|rule| rule.id == "removed-rule"),
        "an orphan override does not create an active rule"
    );
    assert!(diagnostics.is_empty(), "valid overrides: {diagnostics:?}");

    let _ = std::fs::remove_dir_all(&repo);
    if let Some(user_dir) = user_file.parent() {
        let _ = std::fs::remove_dir_all(user_dir);
    }
}

#[test]
fn invalid_override_severity_is_a_gate_blocking_loader_diagnostic() {
    let _env_lock = ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let repo = tempdir("invalid-severity-repo");
    let home = tempdir("invalid-severity-home");
    let user_file = home.join("overrides.toml");
    let repo_file = repo.join(".varde-code/overrides.toml");
    let rule_id = "file-complexity-hotspot";
    let mut env = EnvGuard::new();
    env.set("HOME", home.as_os_str());
    env.set("VARDE_CONFIG_DIR", home.join("varde-config").as_os_str());
    env.set("VARDE_CODE_USER_OVERRIDES_FILE", user_file.as_os_str());

    write(&repo.join("main.rs"), "");
    write(&user_file, "");
    write(
        &repo_file,
        &format!("[rules.{rule_id}]\nseverity = \"critical\"\n"),
    );

    let db_path = varde_code::db::path::repo_db_path(&repo);
    varde_code::build_index_at(repo.to_str().expect("repo path is UTF-8"), &db_path)
        .expect("build isolated index");
    let payload = varde_code::scan_cli::scan_repo(&serde_json::json!({
        "repoRoot": repo.display().to_string(),
    }))
    .expect("scan returns loader diagnostics");

    let diagnostics = payload["diagnostics"]
        .as_array()
        .expect("diagnostics array");
    let diagnostic = diagnostics
        .iter()
        .find(|diagnostic| diagnostic["rule_id"] == rule_id)
        .expect("invalid override diagnostic names its rule");
    let reported_file = diagnostic["file"].as_str().expect("diagnostic file path");
    assert!(
        reported_file.ends_with(".varde-code/overrides.toml"),
        "diagnostic names the repo overrides file: {diagnostic:?}"
    );
    assert!(
        diagnostic["reason"]
            .as_str()
            .expect("diagnostic reason")
            .contains("invalid severity")
    );
    assert_eq!(diagnostic["blocking"], true);
    assert_eq!(diagnostic["severity"], "error");
    assert_eq!(diagnostic["location"]["file"], reported_file);
    assert!(
        payload["gate"]["blocking_diagnostic_count"]
            .as_u64()
            .expect("blocking diagnostic count")
            > 0
    );
    assert_eq!(payload["analysis"]["status"], "incomplete");

    let _ = std::fs::remove_dir_all(&repo);
    let _ = std::fs::remove_dir_all(&home);
}
