//! Self-invoked and written commands keep their argument forms and only swap
//! the executable, so they must work through `varde` and its hidden aliases.
//! Every case runs against a temp HOME and temp TOZ_CONFIG_DIR.

use assert_cmd::Command;
use std::fs;
use std::path::PathBuf;

struct Env {
    root: tempfile::TempDir,
}

impl Env {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        for dir in ["home/.config", "cfg", "project", "repo/src"] {
            fs::create_dir_all(root.path().join(dir)).unwrap();
        }
        Self { root }
    }

    fn path(&self, rel: &str) -> PathBuf {
        self.root.path().join(rel)
    }

    fn cmd(&self, bin: &str) -> Command {
        let mut command = Command::cargo_bin(bin).unwrap();
        command
            .env("HOME", self.path("home"))
            .env("XDG_CONFIG_HOME", self.path("home/.config"))
            .env("TOZ_CONFIG_DIR", self.path("cfg"))
            .env_remove("PI_CODING_AGENT_DIR");
        command
    }

    fn ok(&self, bin: &str, args: &[&str]) -> String {
        let output = self.cmd(bin).args(args).output().unwrap();
        assert!(
            output.status.success(),
            "{bin} {args:?}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        String::from_utf8(output.stdout).unwrap()
    }
}

#[test]
fn toz_worker_reexecs_through_varde() {
    let env = Env::new();
    let project = env.path("project");
    let out = env.ok(
        "varde",
        &[
            "run",
            "--project",
            project.to_str().unwrap(),
            "--json",
            "run",
            "--code",
            "print('worker-ok')",
        ],
    );
    assert_eq!(out.trim(), "worker-ok");
}

#[test]
fn watch_is_reachable_by_hidden_alias_and_setup_path() {
    let env = Env::new();
    for args in [
        ["watch", "--list"].as_slice(),
        ["setup", "watch", "--list"].as_slice(),
    ] {
        let out = env.ok("varde", args);
        assert!(out.contains(r#""ok":true"#), "{args:?}: {out}");
    }
}

#[test]
fn capture_note_and_event_resolve_through_the_hidden_aliases() {
    let env = Env::new();
    for verb in ["capture", "note", "event"] {
        env.ok("varde", &[verb, "--help"]);
    }
}

fn build_and_query(builder: &[&str], bin_builder: &str, bin_query: &str, query_prefix: &[&str]) {
    let env = Env::new();
    let repo = env.path("repo");
    fs::write(repo.join("src/lib.rs"), "pub fn hello() {}\n").unwrap();
    let repo = repo.to_str().unwrap();
    env.ok(
        bin_builder,
        &[builder, &["build", "--repo-root", repo]].concat(),
    );
    let json = format!(r#"{{"repoRoot":"{repo}","filePath":"src/lib.rs"}}"#);
    let out = env.ok(
        bin_query,
        &[query_prefix, &["symbols_in_file", "--json", &json]].concat(),
    );
    assert!(
        out.contains(r#""outcome":"success""#) && out.contains("hello"),
        "{out}"
    );
}

#[test]
fn index_built_by_varde_map_is_fresh_through_varde_map() {
    build_and_query(&["map"], "varde", "varde", &["map"]);
}
