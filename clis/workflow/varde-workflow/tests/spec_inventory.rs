mod common;

use serde_json::Value;
use sha1::{Digest, Sha1};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

struct Fixture {
    root: PathBuf,
    repository: PathBuf,
    knowledge: PathBuf,
    working: PathBuf,
}

impl Fixture {
    fn new(tag: &str) -> Self {
        let root = common::temp_bundle(tag);
        let repository = root.join("repo");
        let knowledge = root.join("knowledge");
        let working = root.join("working");
        for path in [&repository, &knowledge.join("specs"), &working] {
            fs::create_dir_all(path).unwrap();
        }
        git(&repository, &["init", "-q"]);
        git(
            &repository,
            &["config", "user.email", "test@example.invalid"],
        );
        git(&repository, &["config", "user.name", "Test"]);
        for domain in ["a", "b"] {
            let path = repository.join(format!("src/{domain}/main.rs"));
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(&path, format!("fn {domain}() {{}}\n")).unwrap();
            self_spec(
                &repository,
                &knowledge,
                domain,
                &[format!("src/{domain}/main.rs")],
            );
        }
        git(&repository, &["add", "."]);
        git(&repository, &["commit", "-qm", "initial"]);
        Self {
            root,
            repository,
            knowledge,
            working,
        }
    }

    fn inventory(&self, refresh: bool) -> Value {
        self.inventory_with_ack(refresh, None)
    }

    fn inventory_with_ack(&self, refresh: bool, acknowledged: Option<&str>) -> Value {
        let mut command = Command::new(common::bin());
        command
            .args(["spec", "inventory", "--repository"])
            .arg(&self.repository)
            .arg("--knowledge")
            .arg(&self.knowledge)
            .arg("--working")
            .arg(&self.working);
        if refresh {
            command.arg("--refresh");
        }
        if let Some(path) = acknowledged {
            command.arg("--acknowledge-architecture-path").arg(path);
        }
        let output = command.arg("--json").output().unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        common::json_data(&output.stdout)
    }

    fn cache_file(&self) -> PathBuf {
        fs::read_dir(self.working.join("spec-inventory"))
            .unwrap()
            .next()
            .unwrap()
            .unwrap()
            .path()
    }
}

fn git(root: &Path, args: &[&str]) {
    let output = Command::new("git")
        .args(args)
        .current_dir(root)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "git {}: {}",
        args.join(" "),
        String::from_utf8_lossy(&output.stderr)
    );
}

fn blob_hash(bytes: &[u8]) -> String {
    let mut sha = Sha1::new();
    sha.update(format!("blob {}\0", bytes.len()));
    sha.update(bytes);
    format!("{:x}", sha.finalize())
}

fn self_spec(repository: &Path, knowledge: &Path, domain: &str, files: &[String]) {
    let mut sources = String::new();
    let mut aggregate = String::new();
    let mut coverage = String::new();
    for file in files {
        let hash = blob_hash(&fs::read(repository.join(file)).unwrap());
        sources.push_str(&format!("  - path: {file}\n    hash: {hash}\n"));
        aggregate.push_str(&format!("{file}{hash}"));
        coverage.push_str(&format!("  - {file}\n"));
    }
    let root = format!("src/{domain}");
    fs::write(
        knowledge.join("specs").join(format!("{domain}.md")),
        format!("---\ntype: spec\nid: specs/{domain}\ndomain: {domain}\nsource_roots:\n  - {root}\ncovered_paths:\n{coverage}source_hash: {}\nsources:\n{sources}---\nBody\n", blob_hash(aggregate.as_bytes())),
    ).unwrap();
}

fn architecture_spec(repository: &Path, knowledge: &Path) {
    let path = "Cargo.toml";
    let hash = blob_hash(&fs::read(repository.join(path)).unwrap());
    let aggregate = blob_hash(format!("{path}{hash}").as_bytes());
    fs::write(
        knowledge.join("specs/architecture.md"),
        format!("---\ntype: spec\nid: specs/architecture\ndomain: architecture\nsource_roots:\n  - Cargo.toml\ncovered_paths:\n  - Cargo.toml\nsource_hash: {aggregate}\nsources:\n  - path: Cargo.toml\n    hash: {hash}\n---\nBody\n"),
    )
    .unwrap();
}

fn status<'a>(data: &'a Value, name: &str) -> &'a str {
    data["domains"]
        .as_array()
        .unwrap()
        .iter()
        .find(|domain| domain["domain"] == name)
        .unwrap()["status"]
        .as_str()
        .unwrap()
}

#[test]
fn scoped_changes_reuse_unaffected_domain_and_match_refresh() {
    let fixture = Fixture::new("spec-inventory-scoped");
    let cold = fixture.inventory(false);
    assert_eq!(cold["cache_hit"], false);
    assert_eq!(status(&cold, "a"), "reuse");
    assert_eq!(status(&cold, "b"), "reuse");
    assert_eq!(fixture.inventory(false)["cache_hit"], true);

    fs::write(
        fixture.repository.join("src/a/main.rs"),
        "fn changed() {}\n",
    )
    .unwrap();
    let warm = fixture.inventory(false);
    assert_eq!(warm["cache_hit"], true);
    assert_eq!(status(&warm, "a"), "stale");
    assert_eq!(status(&warm, "b"), "reuse");
    let forced = fixture.inventory(true);
    assert_eq!(forced["cache_hit"], false);
    assert_eq!(warm["domains"], forced["domains"]);

    git(&fixture.repository, &["add", "src/a/main.rs"]);
    assert_eq!(status(&fixture.inventory(false), "b"), "reuse");
    git(&fixture.repository, &["commit", "-qm", "changed a"]);
    assert_eq!(status(&fixture.inventory(false), "b"), "reuse");
}

#[test]
fn untracked_content_and_spec_edits_invalidate_cached_verdicts() {
    let fixture = Fixture::new("spec-inventory-untracked");
    let extra = fixture.repository.join("src/a/extra.rs");
    fs::write(&extra, "fn extra() {}\n").unwrap();
    self_spec(
        &fixture.repository,
        &fixture.knowledge,
        "a",
        &["src/a/extra.rs".into(), "src/a/main.rs".into()],
    );
    let first = fixture.inventory(false);
    assert_eq!(status(&first, "a"), "reuse");
    fs::write(&extra, "fn changed_extra() {}\n").unwrap();
    let warm = fixture.inventory(false);
    assert_eq!(warm["cache_hit"], true);
    assert_eq!(status(&warm, "a"), "stale");
    assert_eq!(status(&warm, "b"), "reuse");
    assert_eq!(warm["domains"], fixture.inventory(true)["domains"]);

    let spec = fixture.knowledge.join("specs/b.md");
    let body = fs::read_to_string(&spec)
        .unwrap()
        .replace("source_hash: ", "source_hash: wrong-");
    fs::write(spec, body).unwrap();
    let changed_spec = fixture.inventory(false);
    assert_eq!(status(&changed_spec, "b"), "stale");
    assert_eq!(changed_spec["domains"], fixture.inventory(true)["domains"]);
}

#[test]
fn additions_deletions_and_corrupt_cache_fail_closed() {
    let fixture = Fixture::new("spec-inventory-corrupt");
    fixture.inventory(false);
    fs::write(fixture.repository.join("src/a/new.rs"), "fn new() {}\n").unwrap();
    let added = fixture.inventory(false);
    assert_eq!(status(&added, "a"), "stale");
    assert_eq!(status(&added, "b"), "reuse");
    assert_eq!(added["domains"], fixture.inventory(true)["domains"]);

    fs::remove_file(fixture.repository.join("src/b/main.rs")).unwrap();
    let deleted = fixture.inventory(false);
    assert_eq!(status(&deleted, "b"), "stale");
    assert_eq!(deleted["domains"], fixture.inventory(true)["domains"]);

    fs::write(fixture.cache_file(), b"{not-json").unwrap();
    let recovered = fixture.inventory(false);
    assert_eq!(recovered["cache_hit"], false);
    assert_eq!(recovered["domains"], fixture.inventory(true)["domains"]);
    let mut altered: Value =
        serde_json::from_slice(&fs::read(fixture.cache_file()).unwrap()).unwrap();
    altered["cache"]["domains"][0]["status"] = Value::from("reuse");
    fs::write(fixture.cache_file(), serde_json::to_vec(&altered).unwrap()).unwrap();
    assert_eq!(fixture.inventory(false)["cache_hit"], false);
    assert!(fixture.root.is_dir());
}

#[test]
fn roots_architecture_and_due_validation_invalidate_safely() {
    let fixture = Fixture::new("spec-inventory-architecture");
    fixture.inventory(false);
    let architecture = fixture.knowledge.join("specs/architecture.md");
    fs::write(&architecture, "---\ntype: spec\ndomain: architecture\nsource_roots:\n  - Cargo.toml\ncovered_paths: []\nsource_hash: none\nsources: []\n---\nBody\n").unwrap();
    let with_architecture = fixture.inventory(false);
    assert_eq!(status(&with_architecture, "architecture"), "stale");
    assert_eq!(
        with_architecture["domains"],
        fixture.inventory(true)["domains"]
    );

    fs::write(
        fixture.repository.join("Cargo.toml"),
        "[package]\nname = \"fixture\"\n",
    )
    .unwrap();
    let declaration = fixture.inventory(false);
    assert_eq!(status(&declaration, "architecture"), "stale");
    assert_eq!(declaration["domains"], fixture.inventory(true)["domains"]);

    architecture_spec(&fixture.repository, &fixture.knowledge);
    assert_eq!(status(&fixture.inventory(false), "architecture"), "reuse");
    fs::create_dir_all(fixture.repository.join("infra")).unwrap();
    fs::write(
        fixture.repository.join("infra/deploy.yaml"),
        "service: fixture\n",
    )
    .unwrap();
    let new_declaration = fixture.inventory(false);
    assert_eq!(status(&new_declaration, "architecture"), "stale");
    assert_eq!(
        new_declaration["domains"],
        fixture.inventory(true)["domains"]
    );

    let spec = fixture.knowledge.join("specs/a.md");
    let body = fs::read_to_string(&spec)
        .unwrap()
        .replace("  - src/a\n", "  - src/b\n");
    fs::write(spec, body).unwrap();
    let changed_roots = fixture.inventory(false);
    assert_eq!(status(&changed_roots, "a"), "stale");
    assert_eq!(changed_roots["domains"], fixture.inventory(true)["domains"]);

    for _ in 0..10 {
        fixture.inventory(false);
    }
    let due = fixture.inventory(false);
    assert_eq!(due["full_validation_due"], true);
    assert_eq!(due["full_validation"], true);
    assert_eq!(due["cache_hit"], false);
}

#[test]
fn nested_sources_index_and_ignore_changes_are_not_trusted_hits() {
    let fixture = Fixture::new("spec-inventory-inputs");
    fixture.inventory(false);
    let nested = "clis/workflow/member/src/lib.rs";
    fs::create_dir_all(fixture.repository.join("clis/workflow/member/src")).unwrap();
    fs::write(fixture.repository.join(nested), "pub fn member() {}\n").unwrap();
    let nested_result = fixture.inventory(false);
    assert!(
        nested_result["unmatched"]
            .as_array()
            .unwrap()
            .contains(&Value::from(nested))
    );
    assert!(
        nested_result["missing"]
            .as_array()
            .unwrap()
            .contains(&Value::from("clis/workflow/member"))
    );

    fs::write(
        fixture.knowledge.join("specs/index.md"),
        "---\nsource_commit: old\n---\n",
    )
    .unwrap();
    let index_added = fixture.inventory(false);
    assert_eq!(index_added["cache_hit"], false);
    fs::write(
        fixture.knowledge.join("specs/index.md"),
        "---\nsource_commit: new\n---\n",
    )
    .unwrap();
    assert_eq!(fixture.inventory(false)["full_validation"], true);

    fs::write(fixture.repository.join(".gitignore"), "src/a/ignored.rs\n").unwrap();
    assert_eq!(fixture.inventory(false)["full_validation"], true);
    fs::write(
        fixture.repository.join("src/a/ignored.rs"),
        "fn ignored() {}\n",
    )
    .unwrap();
    assert_eq!(status(&fixture.inventory(false), "a"), "reuse");
    fs::write(fixture.repository.join(".gitignore"), "").unwrap();
    let unignored = fixture.inventory(false);
    assert_eq!(unignored["cache_hit"], false);
    assert_eq!(status(&unignored, "a"), "stale");
    assert_eq!(unignored["domains"], fixture.inventory(true)["domains"]);

    let exclude = fixture.repository.join(".git/info/exclude");
    fs::write(exclude, "*.scratch\n").unwrap();
    assert_eq!(fixture.inventory(false)["full_validation"], true);
}

#[test]
fn new_declaration_outside_architecture_roots_is_stale_on_warm_and_full() {
    for declaration in [
        "k8s/service.yaml",
        "helm/Chart.yaml",
        "terraform/main.tf",
        "go.mod",
    ] {
        let fixture = Fixture::new("spec-inventory-declaration");
        fs::write(fixture.repository.join("Cargo.toml"), "[workspace]\n").unwrap();
        architecture_spec(&fixture.repository, &fixture.knowledge);
        assert_eq!(status(&fixture.inventory(false), "architecture"), "reuse");
        let path = fixture.repository.join(declaration);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, "deployment: changed\n").unwrap();
        let warm = fixture.inventory(false);
        assert_eq!(warm["cache_hit"], true, "{declaration}");
        assert_eq!(status(&warm, "architecture"), "stale", "{declaration}");
        assert_eq!(
            warm["domains"],
            fixture.inventory(true)["domains"],
            "{declaration}"
        );
    }
}

#[test]
fn committed_only_change_and_rename_match_forced_refresh() {
    let fixture = Fixture::new("spec-inventory-commit-rename");
    fixture.inventory(false);
    fs::write(
        fixture.repository.join("src/a/main.rs"),
        "fn committed() {}\n",
    )
    .unwrap();
    git(&fixture.repository, &["add", "src/a/main.rs"]);
    git(
        &fixture.repository,
        &["commit", "-qm", "change a without inventory"],
    );
    let committed = fixture.inventory(false);
    assert_eq!(committed["cache_hit"], true);
    assert_eq!(status(&committed, "a"), "stale");
    assert_eq!(status(&committed, "b"), "reuse");
    assert_eq!(committed["domains"], fixture.inventory(true)["domains"]);

    git(
        &fixture.repository,
        &["mv", "src/b/main.rs", "src/b/renamed.rs"],
    );
    let renamed = fixture.inventory(false);
    assert_eq!(status(&renamed, "b"), "stale");
    assert_eq!(renamed["domains"], fixture.inventory(true)["domains"]);
}

#[test]
fn cache_does_not_cross_repository_roots() {
    let first = Fixture::new("spec-inventory-first-root");
    let second = Fixture::new("spec-inventory-second-root");
    assert_eq!(first.inventory(false)["cache_hit"], false);
    assert_eq!(first.inventory(false)["cache_hit"], true);

    let output = Command::new(common::bin())
        .args(["spec", "inventory", "--repository"])
        .arg(&second.repository)
        .arg("--knowledge")
        .arg(&first.knowledge)
        .arg("--working")
        .arg(&first.working)
        .arg("--json")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let foreign = common::json_data(&output.stdout);
    assert_eq!(foreign["cache_hit"], false);
    assert_eq!(foreign["domains"], first.inventory(true)["domains"]);
}

#[test]
fn generic_config_without_architecture_spec_is_only_a_candidate() {
    let fixture = Fixture::new("spec-inventory-config-candidate");
    fs::create_dir_all(fixture.repository.join("data")).unwrap();
    fs::write(fixture.repository.join("data/sample.json"), "{}\n").unwrap();
    let result = fixture.inventory(false);
    assert_eq!(result["architecture_status"], "none");
    assert_eq!(
        result["architecture_candidates"],
        serde_json::json!(["data/sample.json"])
    );
    assert!(
        !result["missing"]
            .as_array()
            .unwrap()
            .contains(&Value::from("data"))
    );

    fs::write(fixture.repository.join("Cargo.toml"), "[workspace]\n").unwrap();
    let definite = fixture.inventory(false);
    assert_eq!(definite["architecture_status"], "missing");
    assert_eq!(
        definite["architecture_candidates"],
        serde_json::json!(["data/sample.json"])
    );
}

#[test]
fn unknown_new_paths_require_inspection_and_can_be_acknowledged() {
    let fixture = Fixture::new("spec-inventory-unknown-architecture-path");
    fs::write(fixture.repository.join("Cargo.toml"), "[workspace]\n").unwrap();
    architecture_spec(&fixture.repository, &fixture.knowledge);
    assert_eq!(status(&fixture.inventory(false), "architecture"), "reuse");

    fs::create_dir_all(fixture.repository.join("ops")).unwrap();
    fs::write(
        fixture.repository.join("ops/binding.custom"),
        "unit = api\n",
    )
    .unwrap();
    let warm = fixture.inventory(false);
    assert_eq!(warm["cache_hit"], true);
    assert_eq!(status(&warm, "architecture"), "inspect");
    assert_eq!(
        warm["architecture_inspect_paths"],
        serde_json::json!(["ops/binding.custom"])
    );
    assert!(
        warm["unclassified_paths"]
            .as_array()
            .unwrap()
            .contains(&Value::from("ops/binding.custom"))
    );
    assert_eq!(
        fixture.inventory(false)["unclassified_paths"],
        serde_json::json!([])
    );
    let refreshed = fixture.inventory(true);
    assert_eq!(status(&refreshed, "architecture"), "inspect");
    assert!(
        refreshed["unclassified_paths"]
            .as_array()
            .unwrap()
            .contains(&Value::from("ops/binding.custom"))
    );
    let acknowledged = fixture.inventory_with_ack(false, Some("ops/binding.custom"));
    assert_eq!(status(&acknowledged, "architecture"), "reuse");
    assert_eq!(
        acknowledged["architecture_inspect_paths"],
        serde_json::json!([])
    );
    assert_eq!(status(&fixture.inventory(true), "architecture"), "reuse");

    fs::write(
        fixture.repository.join("ops/binding.custom"),
        "unit = other\n",
    )
    .unwrap();
    assert_eq!(status(&fixture.inventory(false), "architecture"), "inspect");

    fs::remove_file(fixture.repository.join("ops/binding.custom")).unwrap();
    assert_eq!(status(&fixture.inventory(false), "architecture"), "reuse");

    let cold = Fixture::new("spec-inventory-unknown-cold");
    fs::write(cold.repository.join("Cargo.toml"), "[workspace]\n").unwrap();
    architecture_spec(&cold.repository, &cold.knowledge);
    fs::create_dir_all(cold.repository.join("ops")).unwrap();
    fs::write(cold.repository.join("ops/binding.custom"), "unit = api\n").unwrap();
    assert_eq!(status(&cold.inventory(true), "architecture"), "inspect");

    let committed = Fixture::new("spec-inventory-unknown-committed");
    fs::write(committed.repository.join("Cargo.toml"), "[workspace]\n").unwrap();
    architecture_spec(&committed.repository, &committed.knowledge);
    assert_eq!(status(&committed.inventory(false), "architecture"), "reuse");
    fs::create_dir_all(committed.repository.join("ops")).unwrap();
    fs::write(
        committed.repository.join("ops/binding.custom"),
        "unit = api\n",
    )
    .unwrap();
    git(&committed.repository, &["add", "ops/binding.custom"]);
    git(
        &committed.repository,
        &["commit", "-qm", "add unknown path"],
    );
    assert_eq!(
        status(&committed.inventory(false), "architecture"),
        "inspect"
    );
    assert_eq!(
        status(&committed.inventory(true), "architecture"),
        "inspect"
    );

    let indexed = Fixture::new("spec-inventory-unknown-indexed");
    let baseline = Command::new("git")
        .args(["rev-parse", "HEAD"])
        .current_dir(&indexed.repository)
        .output()
        .unwrap();
    assert!(baseline.status.success());
    fs::write(
        indexed.knowledge.join("specs/index.md"),
        format!(
            "---\nsource_commit: {}\n---\n",
            String::from_utf8_lossy(&baseline.stdout).trim()
        ),
    )
    .unwrap();
    fs::write(indexed.repository.join("Cargo.toml"), "[workspace]\n").unwrap();
    architecture_spec(&indexed.repository, &indexed.knowledge);
    fs::create_dir_all(indexed.repository.join("ops")).unwrap();
    fs::write(
        indexed.repository.join("ops/binding.custom"),
        "unit = api\n",
    )
    .unwrap();
    git(&indexed.repository, &["add", "ops/binding.custom"]);
    git(&indexed.repository, &["commit", "-qm", "add unknown path"]);
    assert_eq!(status(&indexed.inventory(true), "architecture"), "inspect");

    let generic = Fixture::new("spec-inventory-ambiguous-config");
    fs::write(generic.repository.join("Cargo.toml"), "[workspace]\n").unwrap();
    architecture_spec(&generic.repository, &generic.knowledge);
    assert_eq!(status(&generic.inventory(false), "architecture"), "reuse");
    fs::create_dir_all(generic.repository.join("data")).unwrap();
    fs::write(generic.repository.join("data/settings.json"), "{}\n").unwrap();
    assert_eq!(status(&generic.inventory(false), "architecture"), "inspect");
    assert_eq!(status(&generic.inventory(true), "architecture"), "inspect");
    assert_eq!(
        status(
            &generic.inventory_with_ack(false, Some("data/settings.json")),
            "architecture"
        ),
        "reuse"
    );
    assert_eq!(status(&generic.inventory(true), "architecture"), "reuse");

    fs::create_dir_all(generic.repository.join("deploy")).unwrap();
    fs::write(generic.repository.join("deploy/README.md"), "notes\n").unwrap();
    let readme = generic.inventory(false);
    assert_eq!(status(&readme, "architecture"), "inspect");
    assert_eq!(
        readme["architecture_inspect_paths"],
        serde_json::json!(["deploy/README.md"])
    );
    assert_eq!(
        status(
            &generic.inventory_with_ack(false, Some("deploy/README.md")),
            "architecture"
        ),
        "reuse"
    );
}
