//! Redirected working/knowledge memory: `paths` resolution and conclusion
//! writes that land outside the project tree.

mod common;

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

/// Every invocation points `VARDE_CONFIG_DIR` at an isolated directory so
/// the developer's real `~/.config/varde/config.toml` never leaks in.
fn run(config_dir: &Path, args: &[&str], env: &[(&str, &Path)]) -> Output {
    let mut command = Command::new(common::bin());
    command
        .args(args)
        .env("VARDE_CONFIG_DIR", config_dir)
        .env_remove("VARDE_WORKING_DIR")
        .env_remove("VARDE_KNOWLEDGE_DIR")
        .env_remove("VARDE_LEARN_STORE");
    for (key, value) in env {
        command.env(key, value);
    }
    command.output().unwrap()
}

/// Like `run`, but from `cwd` instead of the test process's own directory —
/// for the no-`--project` root-resolution chain, which starts from cwd.
fn run_in(cwd: &Path, config_dir: &Path, args: &[&str], env: &[(&str, &Path)]) -> Output {
    let mut command = Command::new(common::bin());
    command
        .args(args)
        .current_dir(cwd)
        .env("VARDE_CONFIG_DIR", config_dir)
        .env_remove("VARDE_WORKING_DIR")
        .env_remove("VARDE_KNOWLEDGE_DIR")
        .env_remove("VARDE_LEARN_STORE");
    for (key, value) in env {
        command.env(key, value);
    }
    command.output().unwrap()
}

fn git(dir: &Path, args: &[&str]) {
    let status = Command::new("git")
        .args(args)
        .current_dir(dir)
        .status()
        .unwrap();
    assert!(status.success(), "git {args:?} failed in {dir:?}");
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

fn conclusion_file(knowledge: &Path, slug: &str) -> Option<PathBuf> {
    fs::read_dir(knowledge.join("conclusions"))
        .ok()?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .find(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.ends_with(&format!("-{slug}.md")))
        })
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
    assert!(!config.join("config.toml").exists());
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn legacy_paths_file_resolves_and_migrates_all_entries_on_paths_write() {
    let (base, root) = project("legacy-config-migration");
    let dir = base.join("config");
    fs::create_dir_all(&dir).unwrap();
    let legacy = dir.join("paths.toml");
    fs::write(
        &legacy,
        format!(
            "[default]\nworking = 'default-working'\ntoz = '/tmp/default-toz'\n\n[project.'{}']\nworking = 'project-working'\nknowledge = 'project-knowledge'\ntoz = '/tmp/project-toz'\n",
            root.display()
        ),
    )
    .unwrap();
    let output = run(
        &dir,
        &["paths", "--project", root.to_str().unwrap(), "--json"],
        &[],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data = common::json_data(&output.stdout);
    assert_eq!(data["working_source"], "project");
    assert!(data["toz"].as_str().unwrap().ends_with("/project-toz"));

    let output = run(
        &dir,
        &["paths", "set", "--default", "--learn", "new-learn"],
        &[],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let text = fs::read_to_string(dir.join("config.toml")).unwrap();
    assert!(text.contains("default-working"), "{text}");
    assert!(text.contains("project-working"), "{text}");
    assert!(text.contains("project-knowledge"), "{text}");
    assert!(text.contains("/tmp/default-toz"), "{text}");
    assert!(text.contains("/tmp/project-toz"), "{text}");
    assert!(text.contains("new-learn"), "{text}");
    assert!(!legacy.exists());
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn xdg_config_home_selects_config_file() {
    let (base, root) = project("xdg-config");
    let xdg = base.join("xdg");
    let output = Command::new(common::bin())
        .args([
            "paths",
            "set",
            "--project",
            root.to_str().unwrap(),
            "--working",
            "xdg-working",
            "--json",
        ])
        .env_remove("VARDE_CONFIG_DIR")
        .env("XDG_CONFIG_HOME", &xdg)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let config = xdg.join("varde/config.toml");
    assert!(config.exists());
    let output = Command::new(common::bin())
        .args(["paths", "--project", root.to_str().unwrap(), "--json"])
        .env_remove("VARDE_CONFIG_DIR")
        .env("XDG_CONFIG_HOME", &xdg)
        .output()
        .unwrap();
    let data = common::json_data(&output.stdout);
    assert_eq!(data["config"], config.to_str().unwrap());
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn new_file_wins_when_both_config_names_exist() {
    let (base, root) = project("both-config-names");
    let dir = base.join("config");
    fs::create_dir_all(&dir).unwrap();
    fs::write(dir.join("paths.toml"), "[default]\nworking = 'old'\n").unwrap();
    fs::write(dir.join("config.toml"), "[default]\nworking = 'new'\n").unwrap();
    let output = run(
        &dir,
        &["paths", "--project", root.to_str().unwrap(), "--json"],
        &[],
    );
    let data = common::json_data(&output.stdout);
    assert_eq!(data["working"], root.join("new").to_str().unwrap());
    assert_eq!(
        data["ignored_legacy_config"],
        dir.join("paths.toml").to_str().unwrap()
    );
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn paths_preserve_usage_limit_as_an_unknown_setting() {
    let (base, root) = project("usage-limit-setting-preserved");
    let dir = base.join("config");
    fs::create_dir_all(&dir).unwrap();
    fs::write(dir.join("config.toml"), "[settings]\nusage_limit = '80%'\n").unwrap();

    let output = run(
        &dir,
        &[
            "paths",
            "set",
            "--project",
            root.to_str().unwrap(),
            "--working",
            "/custom-working",
            "--json",
        ],
        &[],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );

    let text = fs::read_to_string(dir.join("config.toml")).unwrap();
    assert!(text.contains("usage_limit = \"80%\""), "{text}");
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn config_command_is_removed() {
    let (base, _root) = project("config-command-removed");
    let output = run(&base.join("config"), &["config"], &[]);
    assert!(!output.status.success());
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn paths_write_migrates_legacy_file_without_losing_toz() {
    let (base, root) = project("legacy-paths-write");
    let dir = base.join("config");
    fs::create_dir_all(&dir).unwrap();
    let legacy = dir.join("paths.toml");
    fs::write(&legacy, "[default]\ntoz = '/tmp/legacy-toz'\n").unwrap();
    let output = run(
        &dir,
        &[
            "paths",
            "set",
            "--project",
            root.to_str().unwrap(),
            "--working",
            "new-working",
        ],
        &[],
    );
    assert!(output.status.success());
    let text = fs::read_to_string(dir.join("config.toml")).unwrap();
    assert!(text.contains("legacy-toz"), "{text}");
    assert!(text.contains("new-working"), "{text}");
    assert!(!legacy.exists());
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
    let text = fs::read_to_string(config.join("config.toml")).unwrap();
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
        !config.join("config.toml").exists(),
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
fn toz_key_survives_a_working_set_and_reports_in_json() {
    let (base, root) = project("paths-toz");
    let config = base.join("config");
    let root_arg = root.to_str().unwrap();
    let toz = base.join("elsewhere/toz-store");

    let output = run(
        &config,
        &[
            "paths",
            "set",
            "--project",
            root_arg,
            "--toz",
            toz.to_str().unwrap(),
            "--json",
        ],
        &[],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data = common::json_data(&output.stdout);
    assert_eq!(data["toz_source"], "project");
    assert_eq!(data["toz"], toz.to_str().unwrap());

    // Setting an unrelated key (`--working`) must rewrite `config.toml`
    // without dropping the already-recorded `toz` entry.
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
            "--json",
        ],
        &[],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let text = fs::read_to_string(config.join("config.toml")).unwrap();
    assert!(text.contains("toz ="), "toz key dropped on rewrite: {text}");

    let output = run(&config, &["paths", "--project", root_arg, "--json"], &[]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data = common::json_data(&output.stdout);
    assert_eq!(data["toz_source"], "project");
    assert_eq!(data["toz"], toz.to_str().unwrap());
    assert_eq!(data["working_source"], "project");
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn default_entry_keeps_one_key_after_unsetting_the_other() {
    let (base, root) = project("paths-default-unset");
    let config = base.join("config");
    let toz = base.join("elsewhere/toz-store");

    let output = run(
        &config,
        &[
            "paths",
            "set",
            "--default",
            "--working",
            "{project}-working",
            "--toz",
            toz.to_str().unwrap(),
        ],
        &[],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );

    // Unsetting `--toz` must leave `working` in the `[default]` table.
    let output = run(&config, &["paths", "unset", "--default", "--toz"], &[]);
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
    assert!(data["toz"].is_null(), "{data}");
    let text = fs::read_to_string(config.join("config.toml")).unwrap();
    assert!(
        text.contains("working ="),
        "default working key dropped: {text}"
    );

    // Re-set `toz`, then unset `--working`: `toz` must survive that pass.
    let output = run(
        &config,
        &["paths", "set", "--default", "--toz", toz.to_str().unwrap()],
        &[],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let output = run(&config, &["paths", "unset", "--default", "--working"], &[]);
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
    assert_eq!(data["toz_source"], "default");
    assert_eq!(data["toz"], toz.to_str().unwrap());
    let text = fs::read_to_string(config.join("config.toml")).unwrap();
    assert!(text.contains("toz ="), "default toz key dropped: {text}");

    fs::remove_dir_all(base).unwrap();
}

#[test]
fn paths_reports_null_toz_when_unset() {
    let (base, root) = project("paths-toz-unset");
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
    assert!(data["toz"].is_null(), "{data}");
    assert!(data["toz_source"].is_null(), "{data}");
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
    let subject = common::review::approve_plan_configured(&root, &plan, &config, &[]);
    common::review::approve_implementation_configured(&root, &config, &[], &subject);

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
    let conclusion = fs::read_to_string(conclusion_file(&knowledge, "feature").unwrap()).unwrap();
    assert!(conclusion.contains("plan: feature\n"));
    assert!(!conclusion.contains(plan.to_str().unwrap()));
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
    let subject = common::review::approve_plan_configured(
        &root,
        &plan,
        &config,
        &[("VARDE_KNOWLEDGE_DIR", knowledge.as_path())],
    );
    common::review::approve_implementation_configured(
        &root,
        &config,
        &[("VARDE_KNOWLEDGE_DIR", knowledge.as_path())],
        &subject,
    );

    let output = run(
        &config,
        &["conclude", plan.to_str().unwrap(), "--json"],
        &[
            ("VARDE_KNOWLEDGE_DIR", knowledge.as_path()),
            ("VARDE_WORKFLOW_FAIL_AFTER_CONCLUSION_STAGE", Path::new("1")),
        ],
    );
    assert_eq!(output.status.code(), Some(1));
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
    assert!(conclusion_file(&knowledge, "feature").is_some());
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn subdir_of_git_repo_without_memory_bank_roots_at_repo_top() {
    let base = common::temp_bundle("root-git-subdir")
        .canonicalize()
        .unwrap();
    let repo = base.join("repo");
    fs::create_dir_all(&repo).unwrap();
    git(&repo, &["init", "--quiet"]);
    let subdir = repo.join("nested/deep");
    fs::create_dir_all(&subdir).unwrap();
    let config = base.join("config");

    let output = run_in(&subdir, &config, &["paths", "--json"], &[]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data = common::json_data(&output.stdout);
    assert_eq!(data["root"], repo.to_str().unwrap());
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn subdir_of_git_repo_with_paths_toml_redirect_uses_redirected_working() {
    let base = common::temp_bundle("root-git-redirect")
        .canonicalize()
        .unwrap();
    let repo = base.join("repo");
    fs::create_dir_all(&repo).unwrap();
    git(&repo, &["init", "--quiet"]);
    let subdir = repo.join("nested/deep");
    fs::create_dir_all(&subdir).unwrap();
    let config = base.join("config");
    let working = base.join("elsewhere/working");

    let output = run(
        &config,
        &[
            "paths",
            "set",
            "--project",
            repo.to_str().unwrap(),
            "--working",
            working.to_str().unwrap(),
        ],
        &[],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );

    let output = run_in(&subdir, &config, &["paths", "--json"], &[]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data = common::json_data(&output.stdout);
    assert_eq!(data["root"], repo.to_str().unwrap());
    assert_eq!(data["working_source"], "project");
    assert_eq!(data["working"], working.to_str().unwrap());
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn inside_linked_worktree_roots_at_main_checkout() {
    let base = common::temp_bundle("root-git-worktree")
        .canonicalize()
        .unwrap();
    let repo = base.join("repo");
    fs::create_dir_all(&repo).unwrap();
    git(&repo, &["init", "--quiet"]);
    git(&repo, &["config", "user.email", "test@example.com"]);
    git(&repo, &["config", "user.name", "Test"]);
    git(&repo, &["commit", "--allow-empty", "--quiet", "-m", "init"]);
    let linked = base.join("linked");
    git(
        &repo,
        &[
            "worktree",
            "add",
            "--quiet",
            linked.to_str().unwrap(),
            "-b",
            "linked-branch",
        ],
    );
    let subdir = linked.join("nested");
    fs::create_dir_all(&subdir).unwrap();
    let config = base.join("config");

    let output = run_in(&subdir, &config, &["paths", "--json"], &[]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data = common::json_data(&output.stdout);
    assert_eq!(data["root"], repo.to_str().unwrap());
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn linked_worktrees_ignore_legacy_entries_and_edit_repository_memory() {
    let base = common::temp_bundle("root-shared-worktrees")
        .canonicalize()
        .unwrap();
    let repo = base.join("repo");
    fs::create_dir_all(repo.join("memory-bank/knowledge")).unwrap();
    git(&repo, &["init", "--quiet"]);
    git(&repo, &["config", "user.email", "test@example.com"]);
    git(&repo, &["config", "user.name", "Test"]);
    fs::write(repo.join("memory-bank/knowledge/record.md"), "record\n").unwrap();
    git(&repo, &["add", "."]);
    git(&repo, &["commit", "--quiet", "-m", "init"]);
    let shared = base.join("shared");
    let separate = base.join("separate");
    git(
        &repo,
        &[
            "worktree",
            "add",
            "--quiet",
            shared.to_str().unwrap(),
            "-b",
            "shared",
        ],
    );
    git(
        &repo,
        &[
            "worktree",
            "add",
            "--quiet",
            separate.to_str().unwrap(),
            "-b",
            "separate",
        ],
    );
    let nested = repo.join("module/deep");
    fs::create_dir_all(nested.join("memory-bank")).unwrap();
    let config = base.join("config");
    let main_working = base.join("main-working");
    let separate_working = base.join("separate-working");
    let output = run(
        &config,
        &[
            "paths",
            "set",
            "--project",
            repo.to_str().unwrap(),
            "--working",
            main_working.to_str().unwrap(),
        ],
        &[],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    // Simulate an existing config from before memory became repo-scoped.
    use std::io::Write;
    let mut file = fs::OpenOptions::new()
        .append(true)
        .open(config.join("config.toml"))
        .unwrap();
    writeln!(
        file,
        "\n[project.'{}']\nworking = '{}'",
        separate.display(),
        separate_working.display()
    )
    .unwrap();
    for (cwd, expected_root, expected_working) in [
        (&repo, &repo, &main_working),
        (&nested, &repo, &main_working),
        (&shared, &repo, &main_working),
        (&separate, &repo, &main_working),
    ] {
        let output = run_in(cwd, &config, &["paths", "--json"], &[]);
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let data = common::json_data(&output.stdout);
        assert_eq!(data["root"], expected_root.to_str().unwrap());
        assert_eq!(data["working"], expected_working.to_str().unwrap());
        assert_eq!(data["working_source"], "project");
    }
    for args in [
        vec!["paths", "--project", separate.to_str().unwrap(), "--json"],
        vec!["paths", "--project", shared.to_str().unwrap(), "--json"],
    ] {
        let output = run(&config, &args, &[]);
        assert!(output.status.success());
        let data = common::json_data(&output.stdout);
        assert_eq!(data["root"], repo.to_str().unwrap());
        assert_eq!(data["working"], main_working.to_str().unwrap());
        assert_eq!(
            data["knowledge"],
            repo.join("memory-bank/knowledge").to_str().unwrap()
        );
    }
    let replacement = base.join("replacement");
    let output = run(
        &config,
        &[
            "paths",
            "set",
            "--project",
            separate.to_str().unwrap(),
            "--working",
            replacement.to_str().unwrap(),
            "--json",
        ],
        &[],
    );
    assert!(output.status.success());
    let data = common::json_data(&output.stdout);
    assert_eq!(data["root"], repo.to_str().unwrap());
    let output = run_in(&repo, &config, &["paths", "--json"], &[]);
    assert_eq!(
        common::json_data(&output.stdout)["working"],
        replacement.to_str().unwrap()
    );
    let output = run(
        &config,
        &[
            "paths",
            "unset",
            "--project",
            separate.to_str().unwrap(),
            "--working",
            "--json",
        ],
        &[],
    );
    assert!(output.status.success());
    let data = common::json_data(&output.stdout);
    assert_eq!(
        data["working"],
        repo.join("memory-bank/working").to_str().unwrap()
    );
    assert_eq!(data["working_source"], "builtin");
    let output = run(
        &config,
        &[
            "paths",
            "set",
            "--default",
            "--working",
            "vault/{project}/working",
            "--json",
        ],
        &[],
    );
    assert!(output.status.success());
    let output = run_in(&separate, &config, &["paths", "--json"], &[]);
    assert_eq!(
        common::json_data(&output.stdout)["working"],
        repo.join("vault/repo/working").to_str().unwrap()
    );
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn malformed_paths_config_is_reported() {
    let (base, root) = project("invalid-paths-config");
    let config = base.join("config");
    fs::create_dir_all(&config).unwrap();
    fs::write(config.join("config.toml"), "[project\n").unwrap();
    let output = run_in(&root, &config, &["paths", "--json"], &[]);
    assert!(!output.status.success());
    let response: serde_json::Value = serde_json::from_slice(&output.stderr).unwrap();
    assert!(
        response["data"]["error"].to_string().contains("config"),
        "{response}"
    );
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn separate_git_directory_uses_checkout_root() {
    let base = common::temp_bundle("root-separate-git-dir")
        .canonicalize()
        .unwrap();
    let repo = base.join("repo");
    let metadata = base.join("metadata");
    git(
        &base,
        &[
            "init",
            "--quiet",
            "--separate-git-dir",
            metadata.to_str().unwrap(),
            repo.to_str().unwrap(),
        ],
    );
    let nested = repo.join("module/deep");
    fs::create_dir_all(nested.join("memory-bank")).unwrap();
    let config = base.join("config");
    let output = run_in(&nested, &config, &["paths", "--json"], &[]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data = common::json_data(&output.stdout);
    assert_eq!(data["root"], repo.to_str().unwrap());
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn linked_worktrees_with_separate_or_bare_metadata_share_repository_memory() {
    for (bare, relative) in [(false, false), (false, true), (true, false)] {
        let base = common::temp_bundle(if bare {
            "bare-linked-memory"
        } else {
            "separate-linked-memory"
        })
        .canonicalize()
        .unwrap();
        let repo = base.join("repo with spaces");
        if bare {
            git(
                &base,
                &["init", "--bare", "--quiet", repo.to_str().unwrap()],
            );
        } else {
            let metadata = base.join("metadata");
            git(
                &base,
                &[
                    "init",
                    "--quiet",
                    "--separate-git-dir",
                    metadata.to_str().unwrap(),
                    repo.to_str().unwrap(),
                ],
            );
        }
        git(&repo, &["config", "user.email", "test@example.com"]);
        git(&repo, &["config", "user.name", "Test"]);
        if bare {
            // Seed the bare repository with a commit from an ordinary checkout.
            let seed = base.join("seed");
            git(
                &base,
                &[
                    "clone",
                    "--quiet",
                    repo.to_str().unwrap(),
                    seed.to_str().unwrap(),
                ],
            );
            git(
                &seed,
                &[
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "user.name=Test",
                    "commit",
                    "--allow-empty",
                    "--quiet",
                    "-m",
                    "init",
                ],
            );
            git(&seed, &["push", "--quiet", "origin", "HEAD"]);
        } else {
            git(&repo, &["commit", "--allow-empty", "--quiet", "-m", "init"]);
        }
        let linked = base.join("linked with spaces");
        git(
            &repo,
            &[
                "worktree",
                "add",
                "--quiet",
                linked.to_str().unwrap(),
                "-b",
                "linked",
            ],
        );
        if !bare {
            // Git cannot locate the original checkout from separate metadata
            // until its common config explicitly names that checkout.
            assert_eq!(
                varde_workflow_core::memory::repository_memory_root(&linked),
                base.join("metadata")
            );
            git(
                &repo,
                &[
                    "config",
                    "core.worktree",
                    if relative {
                        "../repo with spaces"
                    } else {
                        repo.to_str().unwrap()
                    },
                ],
            );
        }
        let config_dir = base.join("config");
        let memory = base.join("shared-memory");
        let output = run(
            &config_dir,
            &[
                "paths",
                "set",
                "--project",
                repo.to_str().unwrap(),
                "--working",
                memory.to_str().unwrap(),
                "--json",
            ],
            &[],
        );
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        for output in [
            run_in(&linked, &config_dir, &["paths", "--json"], &[]),
            run(
                &config_dir,
                &["paths", "--project", linked.to_str().unwrap(), "--json"],
                &[],
            ),
        ] {
            assert!(
                output.status.success(),
                "{}",
                String::from_utf8_lossy(&output.stderr)
            );
            let data = common::json_data(&output.stdout);
            assert_eq!(data["root"], repo.to_str().unwrap());
            assert_eq!(data["working"], memory.to_str().unwrap());
        }
        // Direct library consumers must agree with CLI discovery.
        let mut config = varde_workflow_core::memory::Config::default();
        config.project_entry_mut(&repo).working = Some(memory.to_str().unwrap().to_owned());
        config.project_entry_mut(&linked).working = Some("obsolete".into());
        let paths =
            varde_workflow_core::memory::MemoryPaths::resolve_with(&linked, &config).unwrap();
        assert_eq!(paths.root, repo);
        assert_eq!(paths.working.path, memory);
        assert!(paths.contains(&linked.join("src/feature.rs")));
        assert!(paths.contains(&repo.join("memory-bank/knowledge/record.md")));
        assert!(paths.contains(&memory.join("plans/example/plan.md")));
        assert!(!paths.contains(&base.join("unrelated/plan.md")));
        fs::remove_dir_all(base).unwrap();
    }
}

#[test]
fn learn_path_is_global_and_uses_learn_cli_precedence() {
    let (base, root) = project("global-learn-path");
    let config = base.join("config");
    fs::create_dir_all(&config).unwrap();
    fs::write(
        config.join("config.toml"),
        format!(
            "[default]\nworking = '/existing-working'\ntoz = '/existing-toz'\n\n[project.'{}']\nworking = '/project-working'\nknowledge = '/project-knowledge'\ntoz = '/project-toz'\nlearn = '/ignored-project-learn'\n",
            root.display()
        ),
    )
    .unwrap();

    let configured_learn = PathBuf::from("global-learn-store");
    let set = run_in(
        &base,
        &config,
        &[
            "paths",
            "set",
            "--learn",
            configured_learn.to_str().unwrap(),
            "--json",
        ],
        &[],
    );
    assert!(
        set.status.success(),
        "{}",
        String::from_utf8_lossy(&set.stderr)
    );
    let set_data = common::json_data(&set.stdout);
    assert_eq!(set_data["default"]["learn"], "global-learn-store");
    let text = fs::read_to_string(config.join("config.toml")).unwrap();
    assert!(text.contains("working = \"/existing-working\""), "{text}");
    assert!(text.contains("toz = \"/existing-toz\""), "{text}");
    assert!(
        text.contains("learn = \"/ignored-project-learn\""),
        "{text}"
    );
    let resolved_learn = base.join(configured_learn);
    let show = run_in(
        &base,
        &config,
        &["paths", "--project", root.to_str().unwrap(), "--json"],
        &[],
    );
    assert!(
        show.status.success(),
        "{}",
        String::from_utf8_lossy(&show.stderr)
    );
    let data = common::json_data(&show.stdout);
    assert_eq!(data["learn"], resolved_learn.to_str().unwrap());
    assert_eq!(data["learn_source"], "default");
    assert_eq!(data["working"], "/project-working");
    assert_eq!(data["knowledge"], "/project-knowledge");
    assert_eq!(data["toz"], "/project-toz");

    let env_learn = base.join("env-learn-store");
    let show = run_in(
        &base,
        &config,
        &["paths", "--project", root.to_str().unwrap(), "--json"],
        &[("VARDE_LEARN_STORE", &env_learn)],
    );
    let data = common::json_data(&show.stdout);
    assert_eq!(data["learn"], env_learn.to_str().unwrap());
    assert_eq!(data["learn_source"], "env");

    let unset = run_in(
        &base,
        &config,
        &["paths", "unset", "--learn", "--json"],
        &[],
    );
    assert!(
        unset.status.success(),
        "{}",
        String::from_utf8_lossy(&unset.stderr)
    );
    let unset_data = common::json_data(&unset.stdout);
    assert_eq!(unset_data["default"]["learn"], serde_json::Value::Null);
    let show = run_in(
        &base,
        &config,
        &["paths", "--project", root.to_str().unwrap(), "--json"],
        &[],
    );
    let data = common::json_data(&show.stdout);
    assert_eq!(data["learn"], config.join("learn").to_str().unwrap());
    assert_eq!(data["learn_source"], "builtin");
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn learn_path_set_and_unset_reject_project_scope() {
    let (base, root) = project("learn-project-rejected");
    let config = base.join("config");
    let learn = base.join("learn-store");
    let blank = run(&config, &["paths", "set", "--learn", "", "--json"], &[]);
    assert!(!blank.status.success());
    assert!(!config.join("config.toml").exists());

    let set = run(
        &config,
        &[
            "paths",
            "set",
            "--learn",
            learn.to_str().unwrap(),
            "--project",
            root.to_str().unwrap(),
            "--json",
        ],
        &[],
    );
    assert!(!set.status.success());
    assert!(!config.join("config.toml").exists());

    let unset = run(
        &config,
        &[
            "paths",
            "unset",
            "--learn",
            "--project",
            root.to_str().unwrap(),
            "--json",
        ],
        &[],
    );
    assert!(!unset.status.success());
    assert!(!config.join("config.toml").exists());
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn learn_path_mixed_mutations_require_explicit_default() {
    let (base, _root) = project("learn-mixed-paths");
    let config = base.join("config");
    let learn = base.join("learn-store");
    let working = base.join("working");

    let rejected_set = run(
        &config,
        &[
            "paths",
            "set",
            "--learn",
            learn.to_str().unwrap(),
            "--working",
            working.to_str().unwrap(),
            "--json",
        ],
        &[],
    );
    assert!(!rejected_set.status.success());
    assert!(!config.join("config.toml").exists());

    let accepted_set = run(
        &config,
        &[
            "paths",
            "set",
            "--learn",
            learn.to_str().unwrap(),
            "--working",
            working.to_str().unwrap(),
            "--default",
            "--json",
        ],
        &[],
    );
    assert!(
        accepted_set.status.success(),
        "{}",
        String::from_utf8_lossy(&accepted_set.stderr)
    );
    let before_unset = fs::read_to_string(config.join("config.toml")).unwrap();
    assert!(before_unset.contains("learn = "), "{before_unset}");
    assert!(before_unset.contains("working = "), "{before_unset}");

    let rejected_unset = run(
        &config,
        &["paths", "unset", "--learn", "--working", "--json"],
        &[],
    );
    assert!(!rejected_unset.status.success());
    assert_eq!(
        fs::read_to_string(config.join("config.toml")).unwrap(),
        before_unset
    );
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn blank_learn_default_is_invalid_unless_environment_overrides_it() {
    let (base, root) = project("blank-learn-path");
    let config = base.join("config");
    fs::create_dir_all(&config).unwrap();
    fs::write(config.join("config.toml"), "[default]\nlearn = '  '\n").unwrap();

    let invalid = run(
        &config,
        &["paths", "--project", root.to_str().unwrap(), "--json"],
        &[],
    );
    assert!(!invalid.status.success());
    let error: serde_json::Value = serde_json::from_slice(&invalid.stderr).unwrap();
    assert!(error["data"]["error"].to_string().contains("default.learn"));

    let env_learn = base.join("env-learn-store");
    let overridden = run(
        &config,
        &["paths", "--project", root.to_str().unwrap(), "--json"],
        &[("VARDE_LEARN_STORE", &env_learn)],
    );
    assert!(
        overridden.status.success(),
        "{}",
        String::from_utf8_lossy(&overridden.stderr)
    );
    let data = common::json_data(&overridden.stdout);
    assert_eq!(data["learn"], env_learn.to_str().unwrap());
    assert_eq!(data["learn_source"], "env");
    fs::remove_dir_all(base).unwrap();
}
