//! Redirected working/knowledge memory: `paths` resolution and conclusion
//! writes that land outside the project tree.

mod common;

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

/// Every invocation points `VARDE_CONFIG_DIR` at an isolated directory so
/// the developer's real `~/.config/varde/paths.toml` never leaks in.
fn run(config_dir: &Path, args: &[&str], env: &[(&str, &Path)]) -> Output {
    let mut command = Command::new(common::bin());
    command
        .args(args)
        .env("VARDE_CONFIG_DIR", config_dir)
        .env_remove("VARDE_WORKING_DIR")
        .env_remove("VARDE_KNOWLEDGE_DIR");
    for (key, value) in env {
        command.env(key, value);
    }
    command.output().unwrap()
}

fn project(tag: &str) -> (PathBuf, PathBuf) {
    let base = common::temp_bundle(tag).canonicalize().unwrap();
    let root = base.join("project");
    fs::create_dir_all(root.join("memory-bank")).unwrap();
    (base, root)
}

fn write_plan(plan_dir: &Path) -> PathBuf {
    fs::create_dir_all(plan_dir).unwrap();
    fs::write(
        plan_dir.join("delta.md"),
        "---\ntype: contract-delta\nschema_version: 1\ncapability: checkout\nsource_plan: feature\n---\n\n## ADDED\n\n### Requirement: submit-order\n\nGiven a cart, When checkout runs, Then one order exists.\n\n## MODIFIED\n\n## REMOVED\n",
    )
    .unwrap();
    let path = plan_dir.join("plan.md");
    fs::write(
        &path,
        "---\ntype: plan\nstatus: active\ncontract_deltas:\n  - delta.md\n---\n\n## Acceptance criteria\n\n- [x] behavior verified\n",
    )
    .unwrap();
    path
}

#[test]
fn paths_reports_builtin_defaults_without_config() {
    let (base, root) = project("paths-builtin");
    let config = base.join("config");
    let output = run(
        &config,
        &["paths", "--project", root.to_str().unwrap(), "--json"],
        &[],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data = common::json_data(&output.stdout);
    assert_eq!(data["working_source"], "builtin");
    assert_eq!(data["knowledge_source"], "builtin");
    assert!(
        data["working"]
            .as_str()
            .unwrap()
            .ends_with("memory-bank/working"),
        "{data}"
    );
    assert!(!config.join("paths.toml").exists());
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn paths_set_writes_user_config_and_env_overrides_it() {
    let (base, root) = project("paths-set");
    let config = base.join("config");
    let root_arg = root.to_str().unwrap();
    let working = base.join("elsewhere/working");
    let output = run(
        &config,
        &[
            "paths",
            "set",
            "--project",
            root_arg,
            "--working",
            working.to_str().unwrap(),
            "--knowledge",
            "~/varde/{project}/knowledge",
            "--json",
        ],
        &[],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let text = fs::read_to_string(config.join("paths.toml")).unwrap();
    assert!(text.contains("[project.\""), "{text}");
    assert!(text.contains("~/varde/{project}/knowledge"), "{text}");
    assert!(
        !root.join("memory-bank/config").exists(),
        "config must stay out of the repo"
    );

    let data = common::json_data(&output.stdout);
    assert_eq!(data["working_source"], "project");
    assert_eq!(data["knowledge_source"], "project");
    assert!(
        data["knowledge"]
            .as_str()
            .unwrap()
            .ends_with("varde/project/knowledge"),
        "{data}"
    );

    let env_knowledge = base.join("env-knowledge");
    let output = run(
        &config,
        &["paths", "--project", root_arg, "--json"],
        &[("VARDE_KNOWLEDGE_DIR", env_knowledge.as_path())],
    );
    let data = common::json_data(&output.stdout);
    assert_eq!(data["knowledge_source"], "env");
    assert_eq!(data["knowledge"], env_knowledge.to_str().unwrap());
    assert_eq!(data["working_source"], "project");

    let output = run(
        &config,
        &[
            "paths",
            "unset",
            "--project",
            root_arg,
            "--working",
            "--knowledge",
        ],
        &[],
    );
    assert!(output.status.success());
    assert!(
        !config.join("paths.toml").exists(),
        "empty config is removed"
    );
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn paths_default_table_applies_to_every_project() {
    let (base, root) = project("paths-default");
    let config = base.join("config");
    let output = run(
        &config,
        &[
            "paths",
            "set",
            "--default",
            "--working",
            "{project}-working",
        ],
        &[],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let output = run(
        &config,
        &["paths", "--project", root.to_str().unwrap(), "--json"],
        &[],
    );
    let data = common::json_data(&output.stdout);
    assert_eq!(data["working_source"], "default");
    assert_eq!(
        data["working"],
        root.join("project-working").to_str().unwrap()
    );
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn conclusion_reads_redirected_working_and_writes_redirected_knowledge() {
    let (base, root) = project("paths-conclude");
    let config = base.join("config");
    let working = base.join("outside/working");
    let knowledge = base.join("outside/knowledge");
    let output = run(
        &config,
        &[
            "paths",
            "set",
            "--project",
            root.to_str().unwrap(),
            "--working",
            working.to_str().unwrap(),
            "--knowledge",
            knowledge.to_str().unwrap(),
        ],
        &[],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let plan = write_plan(&working.join("plans/group/feature"));

    let output = run(
        &config,
        &["conclude", plan.to_str().unwrap(), "--json"],
        &[],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let contract = fs::read_to_string(knowledge.join("contracts/checkout.md")).unwrap();
    assert!(contract.contains("## Requirement: submit-order"));
    assert!(knowledge.join("conclusions/feature.md").exists());
    assert!(
        knowledge
            .join("workflow/post-conclusion/feature.md")
            .exists()
    );
    assert!(
        !root.join("memory-bank/knowledge").exists(),
        "nothing landed in the tree"
    );
    assert!(
        fs::read_to_string(&plan)
            .unwrap()
            .contains("status: completed")
    );

    let output = run(
        &config,
        &["conclusion-status", plan.to_str().unwrap(), "--json"],
        &[],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn interrupted_conclusion_recovers_across_redirected_knowledge() {
    let (base, root) = project("paths-recover");
    let config = base.join("config");
    let knowledge = base.join("outside/knowledge");
    let plan = write_plan(&root.join("memory-bank/working/plans/group/feature"));

    let output = run(
        &config,
        &["conclude", plan.to_str().unwrap(), "--json"],
        &[
            ("VARDE_KNOWLEDGE_DIR", knowledge.as_path()),
            ("VARDE_WORKFLOW_FAIL_AFTER_CONCLUSION_STAGE", Path::new("1")),
        ],
    );
    assert!(!output.status.success());
    assert!(!knowledge.join("contracts/checkout.md").exists());

    let output = run(
        &config,
        &["recover", "--root", root.to_str().unwrap(), "--json"],
        &[("VARDE_KNOWLEDGE_DIR", knowledge.as_path())],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(knowledge.join("contracts/checkout.md").exists());
    assert!(knowledge.join("conclusions/feature.md").exists());
    fs::remove_dir_all(base).unwrap();
}
