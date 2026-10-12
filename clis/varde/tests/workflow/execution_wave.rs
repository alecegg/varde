use super::common;
use std::fs;
use std::process::Command;

#[test]
fn empty_wave_uses_schema_three_inside_envelope() {
    let root = common::temp_bundle("wave-empty");
    fs::create_dir_all(root.join("tasks")).unwrap();
    let output = Command::new(common::bin())
        .arg("plan")
        .arg("execution-wave")
        .arg(&root)
        .arg("--repo-root")
        .arg(&root)
        .arg("--json")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["data"]["schema_version"], 3);
    assert_eq!(value["data"]["next_wave"], serde_json::json!([]));
}

#[test]
fn plan_validation_uses_execution_wave_ownership_declarations() {
    let fixture = Fixture::new("wave-ownership-validation");
    fixture.task_paths("alpha", "[src/alpha]", "[src/new.rs]");
    fs::write(
        fixture.root.join("plan.md"),
        "---\ntype: plan\nstatus: backlog\ngenerated: [src/generated.rs]\n---\n\
         ## Problem\nA workflow fixture.\n\
         ## Solution\nExercise task ownership validation.\n\
         ## Acceptance criteria\n- [ ] The workflow works.\n      (assert: true)\n\
         ## Progress\n- ready\n",
    )
    .unwrap();

    let output = Command::new(common::bin())
        .arg("plan")
        .arg("validate")
        .arg(fixture.root.join("plan.md"))
        .arg("--json")
        .current_dir(&fixture.root)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let envelope: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(envelope["ok"], true);
}

#[test]
fn plan_validation_tolerates_done_task_legacy_modifies_of_deleted_paths() {
    let fixture = Fixture::new("wave-ownership-deleted");
    // The task completed and deleted its declared file, so the path is gone.
    fs::write(
        fixture.root.join("tasks/alpha.md"),
        "---\nstatus: done\nmodifies: [src/removed.rs]\ncreates: []\nrenames: []\n---\n",
    )
    .unwrap();
    fs::write(
        fixture.root.join("plan.md"),
        "---\ntype: plan\nstatus: completed\n---\n\
         ## Problem\nA workflow fixture.\n\
         ## Solution\nExercise done-task ownership validation.\n\
         ## Acceptance criteria\n- [ ] The workflow works.\n      (assert: true)\n\
         ## Progress\n- ready\n",
    )
    .unwrap();

    let output = Command::new(common::bin())
        .arg("plan")
        .arg("validate")
        .arg(fixture.root.join("plan.md"))
        .arg("--json")
        .current_dir(&fixture.root)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let envelope: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(envelope["ok"], true);
}

struct Fixture {
    root: std::path::PathBuf,
    /// HOME for the in-process code index, kept outside `root` so the
    /// read-only snapshot test is not affected by index bookkeeping.
    home: std::path::PathBuf,
    config_dir: std::path::PathBuf,
}

impl Fixture {
    fn new(tag: &str) -> Self {
        let root = common::temp_bundle(tag).canonicalize().unwrap();
        let home = common::temp_bundle(&format!("{tag}-home"));
        let config_dir = common::temp_bundle(&format!("{tag}-config"));
        fs::create_dir_all(root.join("tasks")).unwrap();
        fs::create_dir_all(root.join("src")).unwrap();
        for id in ["alpha", "beta", "gamma"] {
            fs::write(root.join(format!("src/{id}")), "").unwrap();
        }
        Command::new("git")
            .arg("-C")
            .arg(&root)
            .args(["init", "-q"])
            .status()
            .unwrap();
        Command::new("git")
            .arg("-C")
            .arg(&root)
            .args(["add", "src"])
            .status()
            .unwrap();
        Self {
            root,
            home,
            config_dir,
        }
    }

    fn task(&self, id: &str, fields: &str) {
        fs::write(self.root.join(format!("tasks/{id}.md")), format!("---\nstatus: todo\ndepends_on: []\nmodifies: [src/{id}]\ncreates: []\nrenames: []\nverification_resources: []\n{fields}\n---\n")).unwrap();
    }

    fn task_paths(&self, id: &str, modifies: &str, creates: &str) {
        fs::write(
            self.root.join(format!("tasks/{id}.md")),
            format!("---\nstatus: todo\ndepends_on: []\nmodifies: {modifies}\ncreates: {creates}\nrenames: []\nverification_resources: []\n---\n"),
        )
        .unwrap();
    }

    /// blast_radius runs in-process against an index built under `home`;
    /// rebuild it so it matches the files as they are now.
    fn reindex(&self) {
        let build = Command::new(env!("CARGO_BIN_EXE_varde"))
            .args(["map", "build", "--repo-root"])
            .arg(&self.root)
            .env("HOME", &self.home)
            .env("VARDE_CONFIG_DIR", &self.config_dir)
            .current_dir(&self.root)
            .output()
            .unwrap();
        assert!(build.status.success(), "{build:?}");
    }

    fn set_builders(&self, builders: u32) {
        fs::create_dir_all(&self.config_dir).unwrap();
        fs::write(
            self.config_dir.join("config.toml"),
            format!("[orchestration]\nbuilders = {builders}\n"),
        )
        .unwrap();
    }
    fn run_with_args(&self, args: &[&str]) -> std::process::Output {
        self.reindex();
        Command::new(common::bin())
            .arg("plan")
            .arg("execution-wave")
            .arg(&self.root)
            .arg("--repo-root")
            .arg(&self.root)
            .args(args)
            .arg("--json")
            .env("HOME", &self.home)
            .env("VARDE_CONFIG_DIR", &self.config_dir)
            .current_dir(&self.root)
            .output()
            .unwrap()
    }
    fn run(&self) -> std::process::Output {
        self.run_with_args(&[])
    }
    fn data(&self) -> serde_json::Value {
        let output = self.run();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        serde_json::from_slice::<serde_json::Value>(&output.stdout).unwrap()["data"].clone()
    }
}

#[test]
fn successful_empty_graph_uses_git_basename_reach() {
    let f = Fixture::new("wave-empty-graph");
    f.task("alpha", "");
    f.task("beta", "");
    assert_eq!(f.data()["next_wave"], serde_json::json!(["alpha", "beta"]));
    fs::write(f.root.join("src/beta"), "alpha\n").unwrap();
    assert_eq!(f.data()["next_wave"], serde_json::json!(["alpha"]));
}

#[test]
fn malformed_scalar_and_list_types_are_input_errors() {
    for (index, fields) in [
        "status: []",
        "depends_on: alpha",
        "depends_on: [42]",
        "modifies: null",
        "kind: 4",
        "posture: false",
        "owns: 4",
    ]
    .iter()
    .enumerate()
    {
        let f = Fixture::new(&format!("wave-types-{index}"));
        fs::write(
            f.root.join("tasks/alpha.md"),
            format!("---\n{fields}\n---\n"),
        )
        .unwrap();
        let output = f.run();
        assert_eq!(output.status.code(), Some(1), "{fields}");
        let error: serde_json::Value = serde_json::from_slice(&output.stderr).unwrap();
        assert_eq!(error["data"]["error"]["code"], "invalid_input");
    }
}

#[test]
fn null_optional_fields_and_quoted_comma_paths_use_yaml_semantics() {
    let f = Fixture::new("wave-yaml");
    fs::write(f.root.join("tasks/alpha.md"), "---\nstatus: todo\ndepends_on: []\nmodifies: []\ncreates: [\"src/a,b\"]\nrenames: []\nverification_resources: []\nkind:\nposture:\n---\n").unwrap();
    fs::write(f.root.join("tasks/beta.md"), "---\nstatus: todo\ndepends_on: []\nmodifies: []\ncreates:\n- src/a,b\nrenames: []\nverification_resources: []\n---\n").unwrap();
    assert_eq!(
        f.data()["conflicts"][0]["files"],
        serde_json::json!(["src/a,b"])
    );
}

#[test]
fn uncertain_ownership_serializes_every_ready_task() {
    let f = Fixture::new("wave-uncertain");
    std::os::unix::fs::symlink("loop", f.root.join("loop")).unwrap();
    fs::write(f.root.join("tasks/alpha.md"), "---\nstatus: todo\ndepends_on: []\nmodifies: []\ncreates: [missing/../loop/../new]\nrenames: []\nverification_resources: []\n---\n").unwrap();
    f.task("beta", "");
    f.task("gamma", "");
    assert_eq!(f.data()["next_wave"], serde_json::json!(["alpha"]));
}

#[test]
fn cycle_exit_three_and_zero_worker_limit_names_fix() {
    let f = Fixture::new("wave-errors");
    fs::write(
        f.root.join("tasks/alpha.md"),
        "---\ndepends_on: [beta]\n---\n",
    )
    .unwrap();
    fs::write(
        f.root.join("tasks/beta.md"),
        "---\ndepends_on: [alpha]\n---\n",
    )
    .unwrap();
    assert_eq!(f.run().status.code(), Some(3));
    let output = f.run_with_args(&["--max-workers", "0"]);
    assert_eq!(output.status.code(), Some(1));
    let error = String::from_utf8_lossy(&output.stderr);
    assert!(
        error.contains("omit --max-workers to use [orchestration] builders"),
        "{error}"
    );
}

#[test]
fn omitted_max_workers_uses_configured_cap_and_explicit_width_can_exceed_three() {
    let f = Fixture::new("wave-configured-cap");
    for id in ["alpha", "beta", "gamma", "delta", "epsilon"] {
        fs::write(f.root.join(format!("src/{id}")), "").unwrap();
        f.task(id, "");
    }
    f.set_builders(5);

    let output = f.run();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(data["data"]["next_wave"].as_array().unwrap().len(), 5);

    let output = f.run_with_args(&["--max-workers", "4"]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(data["data"]["next_wave"].as_array().unwrap().len(), 4);
}

#[test]
fn configured_worker_width_has_a_floor_of_one() {
    let f = Fixture::new("wave-configured-cap-floor");
    f.task("alpha", "");
    f.task("beta", "");
    f.task("gamma", "");
    f.set_builders(1);

    let output = f.run();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let data: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(data["data"]["next_wave"], serde_json::json!(["alpha"]));
}

fn snapshot(root: &std::path::Path) -> Vec<(std::path::PathBuf, Vec<u8>)> {
    let mut files = Vec::new();
    for entry in fs::read_dir(root).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() {
            files.extend(snapshot(&path));
        } else {
            files.push((path.clone(), fs::read(path).unwrap()));
        }
    }
    files.sort();
    files
}

#[test]
fn advisory_command_changes_no_repository_or_config_files() {
    let f = Fixture::new("wave-readonly");
    f.task("alpha", "");
    f.task("beta", "");
    let before = snapshot(&f.root);
    assert_eq!(f.data()["next_wave"], serde_json::json!(["alpha", "beta"]));
    assert_eq!(snapshot(&f.root), before);
    assert!(!f.root.join("unused-config").exists());
}

#[test]
fn regular_file_ancestors_cannot_be_erased_by_directory_syntax() {
    for (index, owned) in [
        "src/alpha/../new-a",
        "src/alpha/.",
        "src/alpha/",
        "file-link/../new-a",
        "trailing-link",
    ]
    .iter()
    .enumerate()
    {
        let f = Fixture::new(&format!("wave-notdir-{index}"));
        std::os::unix::fs::symlink("src/alpha", f.root.join("file-link")).unwrap();
        std::os::unix::fs::symlink("src/alpha/", f.root.join("trailing-link")).unwrap();
        fs::write(f.root.join("tasks/alpha.md"), format!("---\nmodifies: []\ncreates: [{owned}]\nrenames: []\nverification_resources: []\n---\n")).unwrap();
        f.task("beta", "");
        f.task("gamma", "");
        let data = f.data();
        assert_eq!(data["next_wave"], serde_json::json!(["alpha"]), "{owned}");
        assert!(
            data["reasons"]
                .as_array()
                .unwrap()
                .iter()
                .any(|value| value.as_str().unwrap().contains("not a directory")),
            "{owned}"
        );
    }
}

#[test]
fn prefix_and_glob_overlaps_are_conflicts() {
    for (tag, alpha, beta) in [
        ("wave-prefix-overlap", "[src/]", "[src/beta.rs]"),
        ("wave-glob-overlap", "['src/*.rs']", "[src/beta.rs]"),
    ] {
        let f = Fixture::new(tag);
        f.task_paths("alpha", "[]", alpha);
        f.task_paths("beta", "[]", beta);
        f.task_paths("gamma", "[]", "[src/gamma.rs]");

        let data = f.data();
        assert_eq!(
            data["conflicts"][0]["tasks"],
            serde_json::json!(["alpha", "beta"])
        );
        assert_eq!(
            data["next_wave"],
            serde_json::json!(["alpha"]),
            "{tag}: {data}"
        );
    }
}

#[test]
fn shared_plan_paths_do_not_conflict() {
    let f = Fixture::new("wave-shared-no-conflict");
    fs::write(
        f.root.join("plan.md"),
        "---\ntype: plan\nshared: [build/index.json]\ngenerated: [build/legacy.json]\n---\n",
    )
    .unwrap();
    f.task("alpha", "");
    f.task("beta", "");
    f.task("gamma", "");

    let data = f.data();
    assert!(data["conflicts"].as_array().unwrap().is_empty(), "{data}");
    assert_eq!(data["next_wave"].as_array().unwrap().len(), 3);
}

#[test]
fn source_patterns_keep_dependency_reach_serial() {
    let f = Fixture::new("wave-pattern-source");
    f.task_paths("alpha", "[src/]", "[]");
    f.task_paths("beta", "[]", "[docs/new.md]");
    f.task_paths("gamma", "[]", "[out/new.json]");

    let data = f.data();
    assert_eq!(data["next_wave"], serde_json::json!(["alpha"]));
    assert!(data["reasons"].as_array().unwrap().iter().any(|reason| {
        reason
            .as_str()
            .unwrap()
            .contains("source ownership pattern has unknown dependency reach")
    }));
}
