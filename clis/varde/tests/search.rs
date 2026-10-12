//! `varde search` end to end: a spawned binary over a fixture whose stores
//! all live in temp directories named by environment variables.

use serde_json::Value;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use toz_core::capture::{self, CaptureInput};
use toz_core::config::Config;
use toz_core::index::index_file as index_toz_file;
use toz_core::store::Store;
use varde_learn_core::{FrictionAddMode, FrictionAddRequest};

const TERM: &str = "zebrafish";

struct Fixture {
    root: PathBuf,
    _dir: tempfile::TempDir,
}

impl Fixture {
    fn new() -> Self {
        let dir = tempfile::tempdir().unwrap();
        let root = fs::canonicalize(dir.path()).unwrap();
        let fixture = Self { root, _dir: dir };
        for sub in [
            "home",
            "toz",
            "vcfg",
            "work/plans",
            "know",
            "repo/src",
            "nonrepo",
            "elsewhere",
        ] {
            fs::create_dir_all(fixture.root.join(sub)).unwrap();
        }
        let repo = fixture.repo();
        let git = Command::new("git")
            .args(["init", "-q"])
            .current_dir(&repo)
            .status()
            .unwrap();
        assert!(git.success());
        fs::write(
            repo.join("README.md"),
            format!("# Repo\n\n{TERM} overview\n"),
        )
        .unwrap();
        fs::write(
            repo.join("src/lib.rs"),
            format!("pub fn {TERM}_handler() {{}}\n"),
        )
        .unwrap();
        fixture
    }

    fn repo(&self) -> PathBuf {
        self.root.join("repo")
    }

    fn varde(&self, args: &[&str]) -> Command {
        self.varde_at(&self.repo(), args)
    }

    fn varde_at(&self, cwd: &Path, args: &[&str]) -> Command {
        let mut command = Command::new(env!("CARGO_BIN_EXE_varde"));
        command
            .args(args)
            .current_dir(cwd)
            .env_remove("VARDE_TOZ_CONFIG_DIR")
            .env_remove("XDG_CONFIG_HOME")
            .env("HOME", self.root.join("home"))
            .env("TOZ_CONFIG_DIR", self.root.join("toz"))
            .env("VARDE_CONFIG_DIR", self.root.join("vcfg"))
            .env("VARDE_LEARN_STORE", self.root.join("learn"))
            .env("VARDE_WORKING_DIR", self.root.join("work"))
            .env("VARDE_KNOWLEDGE_DIR", self.root.join("know"));
        command
    }

    fn run(&self, args: &[&str]) -> Output {
        self.varde(args).output().unwrap()
    }

    fn run_with_working(&self, args: &[&str], working: &Path) -> Output {
        self.varde(args)
            .env("VARDE_WORKING_DIR", working)
            .output()
            .unwrap()
    }

    fn index_code(&self) {
        let repo = self.repo();
        let output = self.run(&["map", "build", "--repo-root", repo.to_str().unwrap()]);
        assert!(output.status.success(), "{output:?}");
    }

    /// Stores `text` with `varde run capture --force`, which creates the toz db.
    fn capture(&self, text: &str) {
        let mut child = self
            .varde(&["run", "capture", "--force", "--quiet"])
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .spawn()
            .unwrap();
        child
            .stdin
            .take()
            .unwrap()
            .write_all(text.as_bytes())
            .unwrap();
        assert!(child.wait().unwrap().success());
    }

    fn toz_db(&self) -> PathBuf {
        fs::read_dir(self.root.join("toz"))
            .unwrap()
            .flatten()
            .map(|entry| entry.path().join("toz.db"))
            .find(|path| path.is_file())
            .expect("toz db")
    }

    fn index_file(&self, path: &Path) {
        let mut store = Store::open(&self.toz_db()).unwrap();
        index_toz_file(&Config::default(), &mut store, path, None, None).unwrap();
    }

    fn fetched_page(&self, text: &str) {
        let mut store = Store::open(&self.toz_db()).unwrap();
        let mut input = CaptureInput::new(text.as_bytes(), "https://example.test", "fetch");
        input.force = true;
        capture::run(&Config::default(), &mut store, input, &[]).unwrap();
    }

    fn friction(&self, title: &str) {
        let learn = self.root.join("learn");
        let mut store = varde_learn_core::Store::open(&learn).unwrap();
        store
            .add_friction(FrictionAddRequest {
                mode: FrictionAddMode::Create {
                    source: "test".into(),
                    title: title.into(),
                    target: None,
                    global: true,
                },
                evidence: "evidence".into(),
                cwd: learn,
            })
            .unwrap();
    }

    fn write(&self, rel: &str, body: &str) {
        fs::write(self.root.join(rel), body).unwrap();
    }

    fn full(&self) {
        self.index_code();
        self.write("work/plans/one.md", &format!("# Plan\n\n{TERM} rollout\n"));
        self.write(
            "know/concept.md",
            &format!("---\ntype: decision\ntitle: concept\n---\n# concept\n{TERM} decision\n"),
        );
        self.capture(&format!("{TERM} captured output\n"));
        self.fetched_page(&format!("{TERM} fetched page\n"));
        self.friction(&format!("{TERM} friction"));
    }
}

fn groups(output: &Output) -> Vec<Value> {
    assert!(output.status.success(), "{output:?}");
    let envelope: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(envelope["ok"], true);
    envelope["data"]["groups"].as_array().unwrap().clone()
}

fn group<'a>(groups: &'a [Value], source: &str) -> &'a Value {
    groups
        .iter()
        .find(|g| g["source"] == source)
        .unwrap_or_else(|| panic!("no {source} group"))
}

fn names(groups: &[Value]) -> Vec<&str> {
    groups
        .iter()
        .map(|g| g["source"].as_str().unwrap())
        .collect()
}

#[test]
fn every_source_group_has_a_labeled_hit() {
    let fixture = Fixture::new();
    fixture.full();
    let all = groups(&fixture.run(&["search", TERM, "--json"]));
    assert_eq!(
        names(&all),
        ["code", "docs", "knowledge", "plans", "output", "friction"]
    );
    for g in &all {
        let source = g["source"].as_str().unwrap();
        assert_eq!(g["status"], "ok", "{source}: {g}");
        let hits = g["hits"].as_array().unwrap();
        assert!(!hits.is_empty(), "{source} has no hits");
        assert!(hits.iter().all(|hit| hit["source"] == source), "{g}");
    }
    let output = group(&all, "output")["hits"].as_array().unwrap().clone();
    assert!(
        output.len() >= 2,
        "capture and fetch both found: {output:?}"
    );
}

#[test]
fn missing_code_index_is_unavailable_and_others_return() {
    let fixture = Fixture::new();
    fixture.full();
    // Drop the code index that `full` built.
    fs::remove_dir_all(fixture.root.join("vcfg/code")).unwrap();
    let legacy = fixture.root.join("home/.config/varde-code");
    if legacy.exists() {
        fs::remove_dir_all(legacy).unwrap();
    }
    let all = groups(&fixture.run(&["search", TERM, "--json"]));
    let code = group(&all, "code");
    assert_eq!(code["status"], "unavailable", "{code}");
    assert!(code["reason"].as_str().is_some_and(|r| !r.is_empty()));
    for source in ["docs", "knowledge", "plans", "output", "friction"] {
        assert!(
            !group(&all, source)["hits"].as_array().unwrap().is_empty(),
            "{source}"
        );
    }
}

#[test]
fn in_selects_only_the_named_sources() {
    let fixture = Fixture::new();
    fixture.full();
    let only = groups(&fixture.run(&["search", TERM, "--in", "knowledge", "--json"]));
    assert_eq!(names(&only), ["knowledge"]);
    let two = groups(&fixture.run(&["search", TERM, "--in", "friction,code", "--json"]));
    assert_eq!(names(&two), ["code", "friction"]);
}

#[test]
fn limit_caps_hits_per_source() {
    let fixture = Fixture::new();
    for name in ["a", "b", "c"] {
        fixture.write(
            &format!("work/plans/{name}.md"),
            &format!("{TERM} plan {name}\n"),
        );
    }
    let plans = groups(&fixture.run(&["search", TERM, "--in", "plans", "--limit", "2", "--json"]));
    assert_eq!(group(&plans, "plans")["hits"].as_array().unwrap().len(), 2);
}

#[test]
fn unknown_source_and_zero_limit_are_usage_errors() {
    let fixture = Fixture::new();
    for args in [
        ["search", TERM, "--in", "nope"],
        ["search", TERM, "--limit", "0"],
    ] {
        assert_eq!(fixture.run(&args).status.code(), Some(2), "{args:?}");
    }
}

#[test]
fn text_output_has_a_heading_per_source() {
    let fixture = Fixture::new();
    fixture.write("work/plans/one.md", &format!("{TERM} rollout\n"));
    let output = fixture.run(&["search", TERM, "--in", "plans,friction"]);
    assert!(output.status.success());
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(text.contains("## plans (1)"), "{text}");
    assert!(text.contains("## friction (unavailable)"), "{text}");
}

#[test]
fn docs_excludes_external_and_working_files_before_applying_limit() {
    let fixture = Fixture::new();
    fs::create_dir_all(fixture.repo().join("docs")).unwrap();
    fixture.write("repo/docs/a.md", &format!("{TERM} repository docs\n"));
    let working = fixture.repo().join("working");
    let working_file = working.join("plans/inside.md");
    fs::create_dir_all(working_file.parent().unwrap()).unwrap();
    fs::write(&working_file, format!("{TERM} internal plan\n")).unwrap();

    let initialized =
        fixture.run_with_working(&["search", "no-match", "--in", "docs", "--json"], &working);
    assert!(initialized.status.success(), "{initialized:?}");
    for index in 0..4 {
        let external = fixture.root.join(format!("elsewhere/notes-{index}.md"));
        fs::write(&external, format!("{TERM} ").repeat(20)).unwrap();
        fixture.index_file(&external);
    }
    fixture.index_file(&working_file);

    let docs = groups(&fixture.run_with_working(
        &["search", TERM, "--in", "docs", "--limit", "2", "--json"],
        &working,
    ));
    let hits = group(&docs, "docs")["hits"].as_array().unwrap();
    assert_eq!(
        hits.len(),
        2,
        "repository docs should still fill the limit: {hits:?}"
    );
    assert!(
        hits.iter().all(|hit| {
            let location = hit["location"].as_str().unwrap();
            location.starts_with("README.md:") || location.starts_with("docs/")
        }),
        "non-doc index source leaked into docs: {hits:?}"
    );
}

#[test]
fn non_repository_makes_docs_and_plans_unavailable_without_creating_store() {
    let fixture = Fixture::new();
    let output = fixture
        .varde_at(
            &fixture.root.join("nonrepo"),
            &["search", TERM, "--in", "docs,plans", "--json"],
        )
        .output()
        .unwrap();
    let all = groups(&output);

    assert_eq!(names(&all), ["docs", "plans"]);
    for source in ["docs", "plans"] {
        let result = group(&all, source);
        assert_eq!(result["status"], "unavailable", "{result}");
        assert_eq!(result["reason"], "not a git repository", "{result}");
    }
    assert_eq!(
        fs::read_dir(fixture.root.join("toz")).unwrap().count(),
        0,
        "non-repository search created a toz store"
    );
}

#[test]
fn plans_notice_only_when_markdown_is_present_and_not_yet_indexed() {
    let fixture = Fixture::new();
    fixture.write("work/plans/first.md", &format!("# Plan\n{TERM}\n"));
    let first = fixture.run(&["search", TERM, "--in", "plans", "--json"]);
    assert!(first.status.success(), "{first:?}");
    assert!(
        String::from_utf8_lossy(&first.stderr)
            .contains("indexing plan and review files (first run)"),
        "first run notice missing: {:?}",
        String::from_utf8_lossy(&first.stderr)
    );

    let second = fixture.run(&["search", TERM, "--in", "plans", "--json"]);
    assert!(second.status.success(), "{second:?}");
    assert!(
        !String::from_utf8_lossy(&second.stderr)
            .contains("indexing plan and review files (first run)"),
        "second run repeated notice: {:?}",
        String::from_utf8_lossy(&second.stderr)
    );

    let empty = Fixture::new();
    let empty_store = empty.run(&["search", TERM, "--in", "plans", "--json"]);
    assert!(empty_store.status.success(), "{empty_store:?}");
    assert!(
        !String::from_utf8_lossy(&empty_store.stderr)
            .contains("indexing plan and review files (first run)"),
        "empty working store printed notice: {:?}",
        String::from_utf8_lossy(&empty_store.stderr)
    );
}

#[test]
fn help_describes_the_command() {
    let fixture = Fixture::new();
    let word = fixture.run(&["help", "search"]);
    let flag = fixture.run(&["search", "--help"]);
    assert!(flag.status.success());
    assert_eq!(word.stdout, flag.stdout);
    assert!(String::from_utf8(flag.stdout).unwrap().contains("--in"));
}
