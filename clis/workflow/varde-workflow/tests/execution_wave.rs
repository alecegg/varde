mod common;
use std::fs;
use std::process::Command;

#[test]
fn empty_wave_uses_schema_three_inside_envelope() {
    let root = common::temp_bundle("wave-empty");
    fs::create_dir_all(root.join("tasks")).unwrap();
    let output = Command::new(common::bin())
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

struct Fixture {
    root: std::path::PathBuf,
    bin: std::path::PathBuf,
}

impl Fixture {
    fn new(tag: &str, provider: &str) -> Self {
        use std::os::unix::fs::PermissionsExt;
        let root = common::temp_bundle(tag).canonicalize().unwrap();
        let bin = root.join("bin");
        fs::create_dir_all(&bin).unwrap();
        fs::create_dir_all(root.join("tasks")).unwrap();
        fs::create_dir_all(root.join("src")).unwrap();
        for id in ["alpha", "beta", "gamma"] {
            fs::write(root.join(format!("src/{id}")), "").unwrap();
        }
        let path = bin.join("varde-code");
        fs::write(&path, format!("#!/bin/sh\n{provider}\n")).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
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
        Self { root, bin }
    }

    fn task(&self, id: &str, fields: &str) {
        fs::write(self.root.join(format!("tasks/{id}.md")), format!("---\nstatus: todo\ndepends_on: []\nmodifies: [src/{id}]\ncreates: []\nrenames: []\nverification_resources: []\n{fields}\n---\n")).unwrap();
    }

    fn run(&self) -> std::process::Output {
        let mut paths = vec![self.bin.clone()];
        paths.extend(std::env::split_paths(&std::env::var_os("PATH").unwrap()));
        Command::new(common::bin())
            .arg("execution-wave")
            .arg(&self.root)
            .arg("--repo-root")
            .arg(&self.root)
            .arg("--json")
            .env("PATH", std::env::join_paths(paths).unwrap())
            .env("VARDE_CONFIG_DIR", self.root.join("unused-config"))
            .output()
            .unwrap()
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
fn malformed_provider_response_and_nonzero_success_remain_unknown() {
    for (index, provider) in [
        "printf 'broken'",
        "printf '{\"ok\":true,\"data\":{}}'",
        "printf '{\"ok\":true,\"data\":[42]}'",
        "printf '{\"ok\":true,\"data\":[]}'; exit 1",
        "printf '{\"ok\":true,\"data\":[],\"meta\":{\"truncated\":true}}'",
    ]
    .iter()
    .enumerate()
    {
        let f = Fixture::new(&format!("wave-bad-{index}"), provider);
        f.task("alpha", "");
        f.task("beta", "");
        let data = f.data();
        assert_eq!(data["next_wave"], serde_json::json!(["alpha"]));
        assert!(
            data["reasons"]
                .as_array()
                .unwrap()
                .iter()
                .any(|value| value.as_str().unwrap().contains("blast_radius failed"))
        );
    }
}

#[test]
fn provider_failure_is_local_while_known_independent_tasks_can_run() {
    let f = Fixture::new(
        "wave-local-failure",
        "case \"$3\" in *src/alpha*) exit 1;; esac\nprintf '{\"ok\":true,\"data\":[\"src/unwritten-consumer\"]}'",
    );
    for id in ["alpha", "beta", "gamma"] {
        f.task(id, "");
    }
    assert_eq!(f.data()["next_wave"], serde_json::json!(["beta", "gamma"]));
}

#[test]
fn successful_empty_graph_uses_git_basename_reach() {
    let f = Fixture::new("wave-empty-graph", "printf '{\"ok\":true,\"data\":[]}'");
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
        "verification_resources: {db: test}",
    ]
    .iter()
    .enumerate()
    {
        let f = Fixture::new(&format!("wave-types-{index}"), "exit 1");
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
    let f = Fixture::new("wave-yaml", "printf '{\"ok\":true,\"data\":[]}'");
    fs::write(f.root.join("tasks/alpha.md"), "---\nstatus: todo\ndepends_on: []\nmodifies: []\ncreates: [\"src/a,b\"]\nrenames: []\nverification_resources: []\nkind:\nposture:\n---\n").unwrap();
    fs::write(f.root.join("tasks/beta.md"), "---\nstatus: todo\ndepends_on: []\nmodifies: []\ncreates:\n- src/a,b\nrenames: []\nverification_resources: []\n---\n").unwrap();
    assert_eq!(
        f.data()["conflicts"][0]["files"],
        serde_json::json!(["src/a,b"])
    );
}

#[test]
fn uncertain_ownership_serializes_every_ready_task() {
    let f = Fixture::new("wave-uncertain", "printf '{\"ok\":true,\"data\":[]}'");
    std::os::unix::fs::symlink("loop", f.root.join("loop")).unwrap();
    fs::write(f.root.join("tasks/alpha.md"), "---\nstatus: todo\ndepends_on: []\nmodifies: []\ncreates: [missing/../loop/../new]\nrenames: []\nverification_resources: []\n---\n").unwrap();
    f.task("beta", "");
    f.task("gamma", "");
    assert_eq!(f.data()["next_wave"], serde_json::json!(["alpha"]));
}

#[test]
fn cycle_exit_three_and_worker_limit_input_one() {
    let f = Fixture::new("wave-errors", "exit 1");
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
    let output = Command::new(common::bin())
        .arg("execution-wave")
        .arg(&f.root)
        .arg("--repo-root")
        .arg(&f.root)
        .args(["--max-workers", "4"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
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
    let f = Fixture::new(
        "wave-readonly",
        "test \"$1\" = blast_radius || exit 9\nprintf '{\"ok\":true,\"data\":[]}'",
    );
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
        let f = Fixture::new(
            &format!("wave-notdir-{index}"),
            "printf '{\"ok\":true,\"data\":[]}'",
        );
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
