//! Execution-wave scheduler scenarios that depend on blast-radius answers.
//! Each scenario runs against a temp git repo with task-file fixtures and a
//! fake `ImpactQuery`: unlisted files have no dependents, `None` models a failed query.

use serde_json::{Value, json};
use std::collections::HashMap;
use std::fs;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};
use std::process::Command;
use varde_contracts::ImpactQuery;
use varde_workflow::execution_wave::execution_wave;

struct Radius(HashMap<String, Option<Vec<String>>>);

impl ImpactQuery for Radius {
    fn dependents(&self, _repo_root: &Path, file: &Path) -> Option<Vec<PathBuf>> {
        match self.0.get(file.to_str()?) {
            Some(listed) => Some(listed.as_ref()?.iter().map(PathBuf::from).collect()),
            None => Some(Vec::new()),
        }
    }
}

/// Blast radius per source path; `None` is a failed query.
fn radius(entries: &[(&str, Option<Vec<&str>>)]) -> Option<&'static dyn ImpactQuery> {
    let map = entries
        .iter()
        .map(|(path, listed)| {
            let listed = listed
                .as_ref()
                .map(|files| files.iter().map(ToString::to_string).collect());
            (path.to_string(), listed)
        })
        .collect();
    Some(Box::leak(Box::new(Radius(map))))
}

fn found<'a>(files: &[&'a str]) -> Option<Vec<&'a str>> {
    Some(files.to_vec())
}

/// A plan dir inside a git repo root with tracked `src/` files.
fn plan(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("wave-scenario-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(dir.join("plan/tasks")).unwrap();
    fs::create_dir_all(dir.join("src")).unwrap();
    git(&dir, &["init", "-q"]);
    for file in [
        "alpha",
        "beta",
        "gamma",
        "delta",
        "util",
        "left",
        "right",
        "new-alpha",
    ] {
        fs::write(dir.join("src").join(file), "").unwrap();
    }
    git(&dir, &["add", "src"]);
    dir
}

fn git(root: &Path, args: &[&str]) {
    let status = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .status()
        .unwrap();
    assert!(status.success(), "git {args:?} failed");
}

struct Task {
    status: &'static str,
    depends_on: &'static str,
    owns: &'static str,
    modifies: &'static str,
    creates: &'static str,
    renames: &'static str,
    resources: &'static str,
    kind: &'static str,
    posture: &'static str,
}

impl Default for Task {
    fn default() -> Self {
        Task {
            status: "todo",
            depends_on: "",
            owns: "",
            modifies: "",
            creates: "",
            renames: "",
            resources: "",
            kind: "",
            posture: "",
        }
    }
}

fn task(root: &Path, id: &str, task: Task) {
    let text = format!(
        "---\ntype: task\nstatus: {}\ndepends_on: [{}]\nowns: [{}]\nmodifies: [{}]\ncreates: [{}]\nrenames: [{}]\nverification_resources: [{}]\nkind: {}\nposture: {}\n---\n",
        task.status,
        task.depends_on,
        task.owns,
        task.modifies,
        task.creates,
        task.renames,
        task.resources,
        task.kind,
        task.posture,
    );
    fs::write(root.join(format!("plan/tasks/{id}.md")), text).unwrap();
}

fn modifies(path: &'static str) -> Task {
    Task {
        modifies: path,
        ..Task::default()
    }
}

fn run(root: &Path, impact: Option<&'static dyn ImpactQuery>) -> Value {
    match execution_wave(&root.join("plan"), root, 3, impact) {
        Ok(data) => data,
        Err(error) => panic!("{error}"),
    }
}

fn next_wave(data: &Value) -> usize {
    data["next_wave"].as_array().unwrap().len()
}

fn conflict_files(data: &Value) -> Vec<String> {
    let mut files: Vec<String> = data["conflicts"]
        .as_array()
        .unwrap()
        .iter()
        .flat_map(|conflict| conflict["files"].as_array().unwrap())
        .map(|file| file.as_str().unwrap().to_string())
        .collect();
    files.sort();
    files
}

fn has_reason(data: &Value, wanted: &str) -> bool {
    data["reasons"]
        .as_array()
        .unwrap()
        .iter()
        .any(|reason| reason.as_str().unwrap().contains(wanted))
}

fn alpha_beta_radius() -> Option<&'static dyn ImpactQuery> {
    radius(&[
        ("src/alpha", found(&["src/alpha-test"])),
        ("src/beta", found(&["src/beta-test"])),
    ])
}

#[test]
fn aliased_rename_source_or_destination_conflicts() {
    let root = plan("rename-alias");
    symlink("src", root.join("alias")).unwrap();
    task(
        &root,
        "alpha-renamer",
        Task {
            renames: "alias/alpha -> alias/new.rs",
            ..Task::default()
        },
    );
    task(&root, "beta-source", modifies("src/alpha"));
    task(
        &root,
        "gamma-target",
        Task {
            creates: "src/new.rs",
            ..Task::default()
        },
    );
    let data = run(&root, radius(&[("src/alpha", found(&["src/alpha-test"]))]));
    assert_eq!(data["next_wave"], json!(["alpha-renamer"]));
    assert_eq!(conflict_files(&data), ["src/alpha", "src/new.rs"]);
}

#[test]
fn graph_aliases_conflict_with_canonical_writes() {
    let root = plan("graph-alias");
    symlink("src", root.join("alias")).unwrap();
    task(&root, "alpha", modifies("alias/alpha"));
    task(&root, "beta", modifies("src/beta"));
    let absolute = format!("{}/alias/beta", root.display());
    for graph_path in ["alias/beta", absolute.as_str()] {
        let data = run(
            &root,
            radius(&[
                ("src/beta", found(&["src/beta-test"])),
                ("src/alpha", found(&[graph_path])),
            ]),
        );
        assert_eq!(data["next_wave"], json!(["alpha"]), "{graph_path}");
        assert_eq!(data["conflicts"][0]["files"], json!(["src/beta"]));
    }
}

#[test]
fn unknown_graph_identity_keeps_the_serial_fallback() {
    let root = plan("uncertain-graph");
    symlink("loop", root.join("loop")).unwrap();
    task(&root, "alpha", modifies("src/alpha"));
    task(
        &root,
        "beta",
        Task {
            creates: "src/new.rs",
            ..Task::default()
        },
    );
    let data = run(&root, radius(&[("src/alpha", found(&["loop/graph.rs"]))]));
    assert_eq!(data["next_wave"], json!(["alpha"]));
    assert!(has_reason(&data, "blast_radius failed"));
}

#[test]
fn independent_tasks_form_one_wave_and_a_dependent_waits() {
    let root = plan("independent");
    task(&root, "alpha", modifies("src/alpha"));
    task(&root, "beta", modifies("src/beta"));
    task(
        &root,
        "follow-up",
        Task {
            depends_on: "alpha, beta",
            modifies: "src/gamma",
            ..Task::default()
        },
    );
    let data = run(&root, alpha_beta_radius());
    assert!(
        next_wave(&data) >= 2,
        "independent tasks did not form a wave"
    );
    assert_eq!(data["next_wave"], json!(["alpha", "beta"]));
    assert_eq!(data["ready"], json!(["alpha", "beta"]));
    assert!(data.get("strategy").is_none());
}

#[test]
fn shared_read_only_import_does_not_conflict() {
    let root = plan("shared-import");
    task(&root, "alpha", modifies("src/alpha"));
    task(&root, "beta", modifies("src/beta"));
    let impact = radius(&[
        ("src/alpha", found(&["src/util"])),
        ("src/beta", found(&["src/util"])),
    ]);
    assert!(next_wave(&run(&root, impact)) >= 2);
}

#[test]
fn both_ends_of_a_rename_are_owned() {
    let root = plan("rename-source");
    task(
        &root,
        "renamer",
        Task {
            renames: "src/alpha -> src/new-alpha",
            ..Task::default()
        },
    );
    task(&root, "source-writer", modifies("src/alpha"));
    task(
        &root,
        "target-writer",
        Task {
            creates: "src/new-alpha",
            ..Task::default()
        },
    );
    let impact = radius(&[
        ("src/alpha", found(&["src/alpha-test"])),
        ("src/gamma", found(&["src/gamma-test"])),
        ("src/new-alpha", found(&["src/new-alpha-test"])),
    ]);
    let data = run(&root, impact);
    assert!(next_wave(&data) <= 1);
    assert_eq!(conflict_files(&data), ["src/alpha", "src/new-alpha"]);
}

#[test]
fn glob_owns_verification_resources_do_not_conflict() {
    let root = plan("glob-owns-resources");
    for (id, path) in [("alpha", "src/alpha"), ("beta", "src/beta")] {
        task(
            &root,
            id,
            Task {
                owns: path,
                resources: "db:integration-snapshot",
                ..Task::default()
            },
        );
    }
    let data = run(&root, alpha_beta_radius());
    assert_eq!(next_wave(&data), 2);
    assert!(data["conflicts"].as_array().unwrap().is_empty());
}

#[test]
fn missing_ownership_metadata_forces_serial_execution() {
    let root = plan("missing-ownership");
    fs::write(
        root.join("plan/tasks/alpha.md"),
        "---\nstatus: todo\ndepends_on: []\n---\n",
    )
    .unwrap();
    task(&root, "beta", modifies("src/beta"));
    let data = run(&root, alpha_beta_radius());
    assert_eq!(data["next_wave"], json!(["alpha"]));
    assert!(has_reason(&data, "missing ownership metadata"));
}

#[test]
fn writing_into_another_tasks_blast_radius_serializes_them() {
    let root = plan("conflict");
    let right = format!("{}/src/right", root.display());
    let impact = radius(&[
        ("src/left", found(&[right.as_str()])),
        ("src/right", found(&["src/right-test"])),
    ]);
    task(&root, "left", modifies("src/left"));
    task(&root, "right", modifies("src/right"));
    let data = run(&root, impact);
    assert!(
        next_wave(&data) <= 1,
        "conflict did not fall back to serial"
    );
    assert_eq!(data["next_wave"], json!(["left"]));
    assert_eq!(data["conflicts"][0]["files"], json!(["src/right"]));
}

#[test]
fn reverse_only_impact_catches_conflicts_when_the_consumer_sorts_first() {
    let root = plan("reverse-impact");
    task(&root, "alpha", modifies("src/alpha"));
    task(&root, "beta", modifies("src/beta"));
    let impact = radius(&[
        ("src/alpha", found(&["src/alpha-test"])),
        ("src/beta", found(&["src/alpha"])),
    ]);
    let data = run(&root, impact);
    assert_eq!(data["next_wave"], json!(["alpha"]));
    assert_eq!(data["conflicts"][0]["files"], json!(["src/alpha"]));
}

#[test]
fn a_task_with_no_declared_write_set_never_runs_in_parallel() {
    let root = plan("unknown");
    task(&root, "alpha", modifies("src/alpha"));
    task(&root, "beta", Task::default());
    let impact = radius(&[("src/alpha", found(&["src/alpha-test"]))]);
    assert!(next_wave(&run(&root, impact)) <= 1);
}

#[test]
fn an_empty_blast_radius_falls_back_to_basename_references() {
    let root = plan("no-edges");
    task(&root, "alpha", modifies("src/alpha"));
    task(&root, "beta", modifies("src/beta"));
    let data = run(&root, radius(&[]));
    assert_eq!(data["next_wave"], json!(["alpha", "beta"]));
}

#[test]
fn duplicate_basenames_only_reach_references_in_the_files_skill_tree() {
    let root = plan("duplicate-basename");
    for dir in ["skills/a/evals", "skills/b/evals", "skills/third"] {
        fs::create_dir_all(root.join(dir)).unwrap();
    }
    fs::write(root.join("skills/a/evals/evals.json"), "evals.json\n").unwrap();
    fs::write(root.join("skills/b/evals/evals.json"), "evals.json\n").unwrap();
    fs::write(
        root.join("skills/third/SKILL.md"),
        "See evals.json for the skill configuration.\n",
    )
    .unwrap();
    git(&root, &["add", "skills"]);
    task(&root, "a-edit", modifies("skills/a/evals/evals.json"));
    task(&root, "b-edit", modifies("skills/b/evals/evals.json"));
    let data = run(&root, radius(&[]));
    assert_eq!(data["next_wave"], json!(["a-edit", "b-edit"]));
}

#[test]
fn markdown_content_edits_only_reach_their_own_files() {
    let root = plan("markdown-content");
    fs::create_dir_all(root.join("docs")).unwrap();
    fs::write(root.join("docs/alpha.md"), "alpha\n").unwrap();
    fs::write(root.join("docs/beta.md"), "beta\n").unwrap();
    git(&root, &["add", "docs"]);
    task(&root, "alpha", modifies("docs/alpha.md"));
    task(&root, "beta", modifies("docs/beta.md"));
    let data = run(&root, radius(&[]));
    assert_eq!(data["next_wave"], json!(["alpha", "beta"]));
    assert_eq!(data["wave_mode"], "worktree");
}

#[test]
fn a_single_writing_task_uses_its_own_worktree() {
    let root = plan("single-writing-worktree");
    fs::create_dir_all(root.join("docs")).unwrap();
    fs::write(root.join("docs/only.md"), "only\n").unwrap();
    git(&root, &["add", "docs"]);
    task(&root, "only", modifies("docs/only.md"));
    let data = run(&root, radius(&[]));
    assert_eq!(data["next_wave"], json!(["only"]));
    assert_eq!(data["wave_mode"], "worktree");
}

#[test]
fn a_markdown_rename_reaches_tracked_files_that_mention_its_basename() {
    let root = plan("markdown-rename");
    fs::create_dir_all(root.join("docs")).unwrap();
    fs::write(root.join("docs/guide.md"), "guide\n").unwrap();
    fs::write(root.join("docs/mentions.md"), "See guide.md for details.\n").unwrap();
    git(&root, &["add", "docs"]);
    task(
        &root,
        "rename",
        Task {
            renames: "docs/guide.md -> docs/new-guide.md",
            ..Task::default()
        },
    );
    task(&root, "mentions", modifies("docs/mentions.md"));
    let data = run(&root, radius(&[]));
    assert_eq!(data["next_wave"], json!(["mentions"]));
    assert_eq!(data["conflicts"][0]["files"], json!(["docs/mentions.md"]));
}

#[test]
fn a_failed_graph_call_stays_unknown_even_for_a_fallback_eligible_path() {
    let root = plan("failed-graph");
    task(&root, "alpha", modifies("src/alpha"));
    task(&root, "beta", modifies("src/beta"));
    let impact = radius(&[("src/alpha", None), ("src/beta", found(&["src/beta-test"]))]);
    let data = run(&root, impact);
    assert_eq!(data["next_wave"], json!(["alpha"]));
    let repo_root = root.canonicalize().unwrap();
    let hint = format!(
        "blast_radius failed for src/alpha (impact query unavailable; if the code index is missing run: varde map build --repo-root {})",
        repo_root.display()
    );
    assert!(has_reason(&data, &hint));
}

#[test]
fn tasks_under_one_cargo_toml_share_a_compile_unit_and_need_worktrees() {
    let root = plan("compile-unit");
    for member in ["alpha", "beta"] {
        fs::create_dir_all(root.join(format!("crates/{member}/src"))).unwrap();
        fs::write(root.join(format!("crates/{member}/src/lib.rs")), "").unwrap();
    }
    fs::write(root.join("Cargo.toml"), "").unwrap();
    git(&root, &["add", "Cargo.toml", "crates"]);
    let impact = radius(&[
        (
            "crates/alpha/src/lib.rs",
            found(&["crates/alpha/src/lib.rs-test"]),
        ),
        (
            "crates/beta/src/lib.rs",
            found(&["crates/beta/src/lib.rs-test"]),
        ),
    ]);
    task(&root, "alpha", modifies("crates/alpha/src/lib.rs"));
    task(&root, "beta", modifies("crates/beta/src/lib.rs"));
    let data = run(&root, impact);
    assert_eq!(data["next_wave"], json!(["alpha", "beta"]));
    assert_eq!(data["wave_mode"], "worktree");
}

#[test]
fn glob_owns_posture_has_no_scheduling_effect() {
    let root = plan("glob-owns-posture");
    task(
        &root,
        "alpha",
        Task {
            owns: "src/alpha",
            posture: "refactor",
            ..Task::default()
        },
    );
    task(&root, "beta", modifies("src/beta"));
    let with_posture = run(&root, alpha_beta_radius());
    task(
        &root,
        "alpha",
        Task {
            owns: "src/alpha",
            ..Task::default()
        },
    );
    let without_posture = run(&root, alpha_beta_radius());
    assert_eq!(with_posture["next_wave"], without_posture["next_wave"]);
    assert_eq!(with_posture["wave_mode"], without_posture["wave_mode"]);
    assert_eq!(with_posture["conflicts"], without_posture["conflicts"]);
}

#[test]
fn glob_owns_overlapping_patterns_conflict() {
    let root = plan("glob-owns-conflict");
    task(
        &root,
        "alpha",
        Task {
            owns: "src/b*",
            ..Task::default()
        },
    );
    task(&root, "beta", modifies("src/beta"));
    let data = run(&root, radius(&[]));
    assert_eq!(data["conflicts"][0]["tasks"], json!(["alpha", "beta"]));
    assert_eq!(data["conflicts"][0]["files"], json!(["src/beta"]));
    assert_eq!(data["next_wave"], json!(["alpha"]));
}

#[test]
fn glob_owns_shared_paths_do_not_conflict() {
    let root = plan("glob-owns-shared");
    fs::write(
        root.join("plan/plan.md"),
        "---\ntype: plan\nshared: [src/shared.rs]\n---\n",
    )
    .unwrap();
    task(
        &root,
        "alpha",
        Task {
            owns: "src/a*",
            ..Task::default()
        },
    );
    task(
        &root,
        "beta",
        Task {
            owns: "src/b*",
            ..Task::default()
        },
    );
    let data = run(&root, radius(&[]));
    assert!(data["conflicts"].as_array().unwrap().is_empty());
    assert_eq!(next_wave(&data), 2);
}

#[test]
fn glob_owns_directory_pattern_conflicts_with_exact_file() {
    let root = plan("glob-owns-directory");
    task(
        &root,
        "alpha",
        Task {
            owns: "src/",
            ..Task::default()
        },
    );
    task(&root, "beta", modifies("src/beta"));
    let data = run(&root, radius(&[]));
    assert_eq!(data["conflicts"][0]["files"], json!(["src/beta"]));
    assert_eq!(data["next_wave"], json!(["alpha"]));
}

#[test]
fn waves_are_capped_at_three_workers() {
    let root = plan("capped");
    let ids = ["alpha", "beta", "gamma", "delta"];
    let paths = ["src/alpha", "src/beta", "src/gamma", "src/delta"];
    let tests = [
        "src/alpha-test",
        "src/beta-test",
        "src/gamma-test",
        "src/delta-test",
    ];
    for (id, path) in ids.iter().zip(paths) {
        task(&root, id, modifies(path));
    }
    let entries: Vec<_> = paths
        .iter()
        .zip(tests)
        .map(|(path, test)| (*path, found(&[test])))
        .collect();
    assert_eq!(next_wave(&run(&root, radius(&entries))), 3);
}

#[test]
fn without_an_impact_query_every_wave_is_serial() {
    let root = plan("no-cli");
    task(&root, "alpha", modifies("src/alpha"));
    task(&root, "beta", modifies("src/beta"));
    assert!(next_wave(&run(&root, None)) <= 1);
}

#[test]
fn continuing_after_a_failure_schedules_only_ready_independent_work() {
    let root = plan("continue-after-blocked");
    let impact = || {
        radius(&[
            ("src/beta", found(&["src/beta-test"])),
            ("src/gamma", found(&["src/gamma-test"])),
            ("src/delta", found(&["src/delta-test"])),
        ])
    };
    let write = |failed, independent| {
        task(
            &root,
            "failed",
            Task {
                status: failed,
                modifies: "src/alpha",
                ..Task::default()
            },
        );
        task(
            &root,
            "waiting",
            Task {
                depends_on: "failed",
                modifies: "src/beta",
                ..Task::default()
            },
        );
        task(
            &root,
            "independent-a",
            Task {
                status: independent,
                modifies: "src/gamma",
                ..Task::default()
            },
        );
        task(
            &root,
            "independent-b",
            Task {
                status: independent,
                modifies: "src/delta",
                ..Task::default()
            },
        );
    };
    let still_blocked = json!([{"task":"waiting","dependency":"failed","reason":"blocked"}]);

    write("blocked", "todo");
    let data = run(&root, impact());
    assert_eq!(data["ready"], json!(["independent-a", "independent-b"]));
    assert_eq!(data["next_wave"], json!(["independent-a", "independent-b"]));
    assert_eq!(data["blocked_by_dep"], still_blocked);

    write("blocked", "done");
    let data = run(&root, impact());
    assert_eq!(data["ready"], json!([]));
    assert_eq!(data["next_wave"], json!([]));
    assert_eq!(data["blocked_by_dep"], still_blocked);

    write("done", "done");
    let data = run(&root, impact());
    assert_eq!(data["ready"], json!(["waiting"]));
    assert_eq!(data["next_wave"], json!(["waiting"]));
    assert_eq!(data["blocked_by_dep"], json!([]));
}

#[test]
fn the_shipped_task_template_frontmatter_is_what_the_resolver_parses() {
    // Deliberate test-time read of the shipped skills template (not a source or
    // dependency import): it keeps a change to the template's frontmatter from
    // silently breaking the resolver.
    let template = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../../skills/varde-change/assets/TASK-TEMPLATE.md");
    let text = fs::read_to_string(&template).unwrap();
    let frontmatter = text.split("````").nth(1).unwrap().trim_start();
    let root = plan("template");
    for (id, path) in [
        ("from-template-alpha", "src/alpha"),
        ("from-template-beta", "src/beta"),
    ] {
        let rendered = frontmatter
            .replace("depends_on: [\"<dep-id>\"]", "depends_on: []")
            .replace("owns: []", &format!("owns: [{path}]"));
        fs::write(root.join(format!("plan/tasks/{id}.md")), rendered).unwrap();
    }
    let data = run(&root, alpha_beta_radius());
    assert_eq!(
        data["next_wave"],
        json!(["from-template-alpha", "from-template-beta"])
    );
}
