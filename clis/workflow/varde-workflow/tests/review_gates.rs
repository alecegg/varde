mod common;

use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

struct Fixture {
    root: PathBuf,
    config: PathBuf,
}

impl Fixture {
    fn new(tag: &str) -> Self {
        let root = common::temp_bundle(&format!("review-{tag}"));
        let config = root.join("isolated-config");
        fs::create_dir_all(&config).unwrap();
        Self { root, config }
    }

    fn run(&self, args: &[&str]) -> Output {
        self.run_at(&self.root, args)
    }

    fn run_at(&self, cwd: &Path, args: &[&str]) -> Output {
        Command::new(common::bin())
            .args(args)
            .current_dir(cwd)
            .env("VARDE_CONFIG_DIR", &self.config)
            .output()
            .unwrap()
    }

    fn plan(&self) -> PathBuf {
        let path = self.root.join("memory-bank/working/plans/example/plan.md");
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(
            &path,
            "---\ntype: plan\nstatus: backlog\n---\n\
             ## Problem\nThe original problem.\n\
             ## Solution\nImplement the solution.\n\
             ## Acceptance criteria\n- [ ] The behavior works.\n\
             ## Progress\n- started\n",
        )
        .unwrap();
        path
    }

    fn init_plan(&self, plan: &Path, scope: &str) -> Value {
        let output = self.run(&[
            "review",
            "init",
            "--plan",
            plan.to_str().unwrap(),
            "--repository",
            self.root.to_str().unwrap(),
            "--scope",
            scope,
            "--json",
        ]);
        success(output)
    }

    fn inspect(&self, subject: &str, phase: &str) -> Value {
        let output = self.run(&[
            "review",
            "inspect",
            "--subject",
            subject,
            "--phase",
            phase,
            "--json",
        ]);
        success(output)
    }

    fn record_approved(&self, subject: &str, phase: &str, inspection: &Value) -> Output {
        self.record_approved_with_risk(subject, phase, inspection, false)
    }

    fn record_approved_with_risk(
        &self,
        subject: &str,
        phase: &str,
        inspection: &Value,
        requires_implementation_review: bool,
    ) -> Output {
        let record_path = self.root.join("record.json");
        let mut record = json!({
            "schema_version": 1,
            "phase": phase,
            "reviewer": { "identity": "independent-reviewer", "provenance": "local-agent" },
            "verdict": "approved",
            "unresolved_choices": [],
            "verification_approach": "Run the focused integration case.",
            "verification_rationale": "It exercises the subject boundary.",
            "verification_expected_results": "The expected result is an approved subject check.",
            "structural_risk": if requires_implementation_review { "high" } else { "low" },
            "structural_risk_rationale": "This fixture is isolated.",
            "implementation_review_required": requires_implementation_review,
            "rationale": "The reviewed contract is ready."
        });
        record["subject_id"] = inspection["subject"]["subject_id"].clone();
        record["contract_fingerprint"] = inspection["contract_fingerprint"].clone();
        record["baseline_id"] = inspection["baseline_id"].clone();
        if phase == "implementation" {
            record["change_fingerprint"] = inspection["change_fingerprint"].clone();
            record["coverage"] = json!("entire-subject-change");
        }
        fs::write(&record_path, serde_json::to_vec_pretty(&record).unwrap()).unwrap();
        self.run(&[
            "review",
            "record",
            "--subject",
            subject,
            "--expected-version",
            inspection["version"].as_str().unwrap(),
            "--file",
            record_path.to_str().unwrap(),
            "--json",
        ])
    }

    fn transition(&self, path: &Path, state: &str) -> Output {
        self.run(&["transition", path.to_str().unwrap(), state, "--json"])
    }

    fn approve(&self, subject: &str, phase: &str, final_review: bool) {
        let inspection = self.inspect(subject, phase);
        success(self.record_approved_with_risk(subject, phase, &inspection, final_review));
    }

    fn git_init(&self) {
        let init = Command::new("git")
            .args(["init", "-q"])
            .current_dir(&self.root)
            .status()
            .unwrap();
        assert!(init.success());
        for (key, value) in [
            ("user.email", "review-test@example.invalid"),
            ("user.name", "Review Test"),
        ] {
            let status = Command::new("git")
                .args(["config", key, value])
                .current_dir(&self.root)
                .status()
                .unwrap();
            assert!(status.success());
        }
    }

    fn git_commit(&self, paths: &[&str]) {
        let mut add = Command::new("git");
        add.arg("add").args(paths).current_dir(&self.root);
        assert!(add.status().unwrap().success());
        let commit = Command::new("git")
            .args(["commit", "-qm", "fixture"])
            .current_dir(&self.root)
            .status()
            .unwrap();
        assert!(commit.success());
    }
}

fn success(output: Output) -> Value {
    assert!(
        output.status.success(),
        "status={:?}\nstdout={}\nstderr={}",
        output.status.code(),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    common::json_data(&output.stdout)
}

fn failure(output: Output, exit: i32, code: &str) -> Value {
    assert_eq!(
        output.status.code(),
        Some(exit),
        "stdout={}\nstderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let bytes = if output.stdout.is_empty() {
        &output.stderr
    } else {
        &output.stdout
    };
    let envelope: Value = serde_json::from_slice(bytes).unwrap();
    assert_eq!(envelope["ok"], false);
    assert_eq!(envelope["data"]["error"]["code"], code);
    envelope
}

#[test]
fn missing_approval_blocks_start_check() {
    let fixture = Fixture::new("missing-approval");
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();

    let blocked = failure(
        fixture.run(&[
            "review",
            "check",
            "--subject",
            subject,
            "--checkpoint",
            "start",
            "--json",
        ]),
        4,
        "review_missing",
    );
    assert!(blocked["data"]["error"]["details"]["blockers"].is_array());

    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn blocked_record_reports_choice_without_mutating_evidence() {
    let fixture = Fixture::new("blocked-record");
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    let inspection = fixture.inspect(subject, "pre-edit");
    let record_path = fixture.root.join("blocked.json");
    let mut record = json!({
        "schema_version": 1,
        "phase": "pre-edit",
        "reviewer": { "identity": "independent-reviewer", "provenance": "local-agent" },
        "verdict": "blocked",
        "unresolved_choices": ["Choose the public contract."],
        "verification_approach": "Exercise check output.",
        "verification_rationale": "The blocker is the expected result.",
        "verification_expected_results": "The selected choice appears in the blocker.",
        "structural_risk": "low",
        "structural_risk_rationale": "No source change is covered.",
        "implementation_review_required": false,
        "rationale": "A human choice remains."
    });
    record["subject_id"] = inspection["subject"]["subject_id"].clone();
    record["contract_fingerprint"] = inspection["contract_fingerprint"].clone();
    record["baseline_id"] = inspection["baseline_id"].clone();
    fs::write(&record_path, serde_json::to_vec_pretty(&record).unwrap()).unwrap();
    success(fixture.run(&[
        "review",
        "record",
        "--subject",
        subject,
        "--expected-version",
        inspection["version"].as_str().unwrap(),
        "--file",
        record_path.to_str().unwrap(),
        "--json",
    ]));
    let subject_dir = fixture
        .root
        .join("memory-bank/working/review-gates")
        .join(subject);
    let before_subject = fs::read(subject_dir.join("subject.json")).unwrap();
    let before_record = fs::read(subject_dir.join("pre-edit.json")).unwrap();

    let blocked = failure(
        fixture.run(&[
            "review",
            "check",
            "--subject",
            subject,
            "--checkpoint",
            "start",
            "--json",
        ]),
        4,
        "review_blocked",
    );
    assert_eq!(
        blocked["data"]["error"]["details"]["blockers"][0]["choices"][0],
        "Choose the public contract."
    );
    assert_eq!(
        fs::read(subject_dir.join("subject.json")).unwrap(),
        before_subject
    );
    assert_eq!(
        fs::read(subject_dir.join("pre-edit.json")).unwrap(),
        before_record
    );
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn task_done_review_pending() {
    let fixture = Fixture::new("task-done-review-pending");
    let source = fixture.root.join("src/feature.rs");
    fs::create_dir_all(source.parent().unwrap()).unwrap();
    fs::write(&source, "baseline\n").unwrap();
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    fixture.approve(subject, "pre-edit", true);
    let plan_start = fixture.transition(&plan, "active");
    assert!(
        plan_start.status.success(),
        "stdout={} stderr={}",
        String::from_utf8_lossy(&plan_start.stdout),
        String::from_utf8_lossy(&plan_start.stderr)
    );

    let task = plan.parent().unwrap().join("tasks/feature/task.md");
    fs::create_dir_all(task.parent().unwrap()).unwrap();
    fs::write(
        &task,
        "---\ntype: task\nstatus: todo\nmodifies:\n  - src/feature.rs\n---\nTask\n",
    )
    .unwrap();
    assert!(fixture.transition(&task, "in_progress").status.success());
    let done = fixture.transition(&task, "done");
    assert!(
        done.status.success(),
        "task completion may precede aggregate review: {}",
        String::from_utf8_lossy(&done.stderr)
    );

    let plan_before = fs::read(&plan).unwrap();
    let complete = fixture.transition(&plan, "completed");
    assert_eq!(complete.status.code(), Some(4));
    assert_eq!(fs::read(&plan).unwrap(), plan_before);
    failure(complete, 4, "review_missing");
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn stale_completion() {
    let fixture = Fixture::new("stale-completion");
    let source = fixture.root.join("src/feature.rs");
    fs::create_dir_all(source.parent().unwrap()).unwrap();
    fs::write(&source, "baseline\n").unwrap();
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    fixture.approve(subject, "pre-edit", true);
    assert!(fixture.transition(&plan, "active").status.success());
    fs::write(&source, "reviewed implementation\n").unwrap();
    let inspection = fixture.inspect(subject, "implementation");
    success(fixture.record_approved(subject, "implementation", &inspection));
    fs::write(&source, "changed after final review\n").unwrap();

    let before = fs::read(&plan).unwrap();
    let complete = fixture.transition(&plan, "completed");
    assert_eq!(complete.status.code(), Some(4));
    assert_eq!(fs::read(&plan).unwrap(), before);
    failure(complete, 4, "review_stale_changes");
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn crud_bypass() {
    let fixture = Fixture::new("crud-bypass");
    let plan = fixture.plan();
    let bytes = fs::read(&plan).unwrap();
    let version = varde_workflow_core::occ::version(&bytes);
    let output = fixture.run(&[
        "concept",
        "set-field",
        "--bundle",
        plan.parent().unwrap().to_str().unwrap(),
        "plan",
        "status",
        "active",
        "--expected-version",
        &version,
        "--json",
    ]);
    assert_eq!(output.status.code(), Some(4));
    assert_eq!(fs::read(&plan).unwrap(), bytes);
    failure(output, 4, "review_missing");
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn artifact_type_alias_create_rejects_unapproved_active_plans() {
    let fixture = Fixture::new("artifact-type-alias-create");
    let bundle = fixture.root.join("memory-bank/working/plans/aliases");
    fs::create_dir_all(&bundle).unwrap();

    for (slug, type_fields) in [
        ("alias-only", "artifact_type: plan\n"),
        ("conflicting-type", "type: reference\nartifact_type: plan\n"),
    ] {
        let input = fixture.root.join(format!("{slug}.md"));
        fs::write(
            &input,
            format!(
                "---\n{type_fields}status: active\ndescription: Active plan.\n---\nPlan body.\n"
            ),
        )
        .unwrap();
        let output = fixture.run(&[
            "concept",
            "create",
            "--bundle",
            bundle.to_str().unwrap(),
            "--file",
            input.to_str().unwrap(),
            "--json",
        ]);
        failure(output, 4, "review_missing");
        assert!(!bundle.join(format!("{slug}.md")).exists());
    }

    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn artifact_type_alias_update_checks_existing_and_proposed_documents() {
    let fixture = Fixture::new("artifact-type-alias-update");
    let plan = fixture.plan();
    let original =
        b"---\ntype: reference\nartifact_type: plan\nstatus: backlog\n---\nOriginal plan.\n";
    fs::write(&plan, original).unwrap();
    let input = fixture.root.join("proposed-plan.md");
    fs::write(
        &input,
        b"---\ntype: reference\nartifact_type: plan\nstatus: active\n---\nProposed plan.\n",
    )
    .unwrap();
    let expected_version = varde_workflow_core::occ::version(original);

    let output = fixture.run(&[
        "concept",
        "update",
        "--bundle",
        plan.parent().unwrap().to_str().unwrap(),
        "plan",
        "--expected-version",
        &expected_version,
        "--file",
        input.to_str().unwrap(),
        "--json",
    ]);

    failure(output, 4, "review_missing");
    assert_eq!(fs::read(&plan).unwrap(), original);
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn artifact_type_alias_set_field_checks_existing_and_proposed_documents() {
    let fixture = Fixture::new("artifact-type-alias-set-field");
    let plan = fixture.plan();
    let original =
        b"---\ntype: reference\nartifact_type: plan\nstatus: backlog\n---\nOriginal plan.\n";
    fs::write(&plan, original).unwrap();
    let expected_version = varde_workflow_core::occ::version(original);

    let output = fixture.run(&[
        "concept",
        "set-field",
        "--bundle",
        plan.parent().unwrap().to_str().unwrap(),
        "plan",
        "status",
        "active",
        "--expected-version",
        &expected_version,
        "--json",
    ]);

    failure(output, 4, "review_missing");
    assert_eq!(fs::read(&plan).unwrap(), original);
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn artifact_type_alias_does_not_gate_unrelated_knowledge() {
    let fixture = Fixture::new("artifact-type-alias-knowledge");
    let bundle = fixture.root.join("memory-bank/working/plans/knowledge");
    fs::create_dir_all(&bundle).unwrap();

    let custom_input = fixture.root.join("custom-knowledge.md");
    fs::write(
        &custom_input,
        "---\ntype: plan\nartifact_type: knowledge\nstatus: active\ndescription: A knowledge note.\n---\nKnowledge.\n",
    )
    .unwrap();
    success(fixture.run(&[
        "concept",
        "create",
        "--bundle",
        bundle.to_str().unwrap(),
        "--file",
        custom_input.to_str().unwrap(),
        "--json",
    ]));

    let typeless_bundle = fixture.root.join("memory-bank/working/plans/typeless");
    fs::create_dir_all(&typeless_bundle).unwrap();
    let typeless_input = fixture.root.join("plan.md");
    fs::write(
        &typeless_input,
        "---\nstatus: active\ndescription: Legacy knowledge.\n---\nLegacy knowledge.\n",
    )
    .unwrap();
    success(fixture.run(&[
        "concept",
        "create",
        "--bundle",
        typeless_bundle.to_str().unwrap(),
        "--file",
        typeless_input.to_str().unwrap(),
        "--json",
    ]));

    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn crud_gates_direct_task_start_and_checks_both_rename_paths() {
    let fixture = Fixture::new("crud-direct-task-start");
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    let task_bundle = plan.parent().unwrap().join("tasks");
    fs::create_dir_all(&task_bundle).unwrap();

    let write_task = |name: &str, ownership: &str| {
        let input = fixture.root.join(format!("{name}.md"));
        fs::write(
            &input,
            format!(
                "---\ntype: task\nstatus: in_progress\ntitle: {name}\ndescription: Exercise task ownership.\n{ownership}---\nTask body.\n"
            ),
        )
        .unwrap();
        fixture.run(&[
            "concept",
            "create",
            "--bundle",
            task_bundle.to_str().unwrap(),
            "--file",
            input.to_str().unwrap(),
            "--json",
        ])
    };

    failure(
        write_task("direct-start", "modifies:\n  - src/feature.rs\n"),
        4,
        "review_missing",
    );
    fixture.approve(subject, "pre-edit", false);
    assert!(
        write_task("direct-start", "modifies:\n  - src/feature.rs\n")
            .status
            .success()
    );

    let missing_ownership = failure(write_task("missing-ownership", ""), 4, "review_invalid");
    assert!(
        missing_ownership["data"]["error"]["message"]
            .as_str()
            .unwrap()
            .contains("non-empty")
    );

    for (name, rename) in [
        (
            "rename-old-outside",
            "renames:\n  - docs/old.rs -> src/new.rs\n",
        ),
        (
            "rename-new-outside",
            "renames:\n  - src/old.rs -> docs/new.rs\n",
        ),
    ] {
        let rejected = failure(write_task(name, rename), 4, "review_invalid");
        assert!(
            rejected["data"]["error"]["message"]
                .as_str()
                .unwrap()
                .contains("falls outside")
        );
        assert!(!task_bundle.join(format!("{name}.md")).exists());
    }

    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn authorized_recovery_commits_an_approved_interrupted_transition_once() {
    let fixture = Fixture::new("authorized-recovery");
    fixture.git_init();
    fs::create_dir_all(fixture.root.join("src")).unwrap();
    fs::write(fixture.root.join("src/tracked.rs"), "baseline\n").unwrap();
    fixture.git_commit(&["src/tracked.rs"]);
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    fixture.approve(subject, "pre-edit", false);

    let interrupted = Command::new(common::bin())
        .args(["transition", plan.to_str().unwrap(), "active", "--json"])
        .current_dir(&fixture.root)
        .env("VARDE_CONFIG_DIR", &fixture.config)
        .env("VARDE_WORKFLOW_FAIL_AFTER_STAGE", "1")
        .output()
        .unwrap();
    assert_eq!(interrupted.status.code(), Some(1));
    assert!(fixture.root.join(".varde-workflow-journal.json").exists());
    let original = fs::read(&plan).unwrap();

    let recovered = fixture.run(&[
        "recover",
        "--root",
        fixture.root.to_str().unwrap(),
        "--json",
    ]);
    assert!(
        recovered.status.success(),
        "{}",
        String::from_utf8_lossy(&recovered.stderr)
    );
    assert_eq!(common::json_data(&recovered.stdout)["recovered"], true);
    assert!(
        fs::read_to_string(&plan)
            .unwrap()
            .contains("status: active")
    );
    assert!(!fixture.root.join(".varde-workflow-journal.json").exists());
    assert_ne!(fs::read(&plan).unwrap(), original);

    let second = fixture.run(&[
        "recover",
        "--root",
        fixture.root.to_str().unwrap(),
        "--json",
    ]);
    assert!(second.status.success());
    assert_eq!(common::json_data(&second.stdout)["recovered"], false);
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn redirected_plan_and_task_transitions_recover_under_the_repository_lock() {
    let fixture = Fixture::new("redirected-transition-recovery");
    let working = fixture.root.with_file_name(format!(
        "{}-external-working",
        fixture.root.file_name().unwrap().to_string_lossy()
    ));
    fs::create_dir_all(&working).unwrap();
    fs::write(
        fixture.config.join("config.toml"),
        format!(
            "[project.{}]\nworking = {}\n",
            serde_json::to_string(fixture.root.to_str().unwrap()).unwrap(),
            serde_json::to_string(working.to_str().unwrap()).unwrap(),
        ),
    )
    .unwrap();
    fs::create_dir_all(fixture.root.join("src")).unwrap();
    fs::write(fixture.root.join("src/feature.rs"), "baseline\n").unwrap();
    let plan = working.join("plans/example/plan.md");
    fs::create_dir_all(plan.parent().unwrap()).unwrap();
    fs::write(
        &plan,
        "---\ntype: plan\nstatus: backlog\n---\n\
         ## Problem\nThe original problem.\n\
         ## Solution\nImplement the solution.\n\
         ## Acceptance criteria\n- [ ] The behavior works.\n",
    )
    .unwrap();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    fixture.approve(subject, "pre-edit", false);

    let interrupted = Command::new(common::bin())
        .args(["transition", plan.to_str().unwrap(), "active", "--json"])
        .current_dir(&fixture.root)
        .env("VARDE_CONFIG_DIR", &fixture.config)
        .env("VARDE_WORKFLOW_FAIL_AFTER_STAGE", "1")
        .output()
        .unwrap();
    assert_eq!(interrupted.status.code(), Some(1));
    assert!(fixture.root.join(".varde-workflow-journal.json").exists());

    let recovered = fixture.run(&[
        "recover",
        "--root",
        fixture.root.to_str().unwrap(),
        "--json",
    ]);
    assert!(
        recovered.status.success(),
        "stdout={} stderr={}",
        String::from_utf8_lossy(&recovered.stdout),
        String::from_utf8_lossy(&recovered.stderr)
    );
    assert!(
        fs::read_to_string(&plan)
            .unwrap()
            .contains("status: active")
    );
    assert!(!fixture.root.join(".varde-workflow-journal.json").exists());

    let task = working.join("plans/example/tasks/feature.md");
    fs::create_dir_all(task.parent().unwrap()).unwrap();
    fs::write(
        &task,
        "---\ntype: task\nstatus: todo\nmodifies:\n  - src/feature.rs\n---\nTask.\n",
    )
    .unwrap();
    let started = fixture.transition(&task, "in_progress");
    assert!(
        started.status.success(),
        "stdout={} stderr={}",
        String::from_utf8_lossy(&started.stdout),
        String::from_utf8_lossy(&started.stderr)
    );

    fs::remove_dir_all(fixture.root).unwrap();
    fs::remove_dir_all(working).unwrap();
}

#[test]
fn prerequisite_conflicts_reject_stale_partial_recovery_and_keep_journal() {
    let fixture = Fixture::new("prerequisite-conflict");
    fixture.git_init();
    fs::create_dir_all(fixture.root.join("src")).unwrap();
    let tracked = fixture.root.join("src/tracked.rs");
    fs::write(&tracked, "baseline\n").unwrap();
    fixture.git_commit(&["src/tracked.rs"]);
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    fixture.approve(subject, "pre-edit", false);

    let interrupted = Command::new(common::bin())
        .args(["transition", plan.to_str().unwrap(), "active", "--json"])
        .current_dir(&fixture.root)
        .env("VARDE_CONFIG_DIR", &fixture.config)
        .env("VARDE_WORKFLOW_FAIL_AFTER_STAGE", "1")
        .output()
        .unwrap();
    assert_eq!(interrupted.status.code(), Some(1));
    let original_plan = fs::read(&plan).unwrap();
    let journal = fixture.root.join(".varde-workflow-journal.json");
    let subject_path = fixture
        .root
        .join("memory-bank/working/review-gates")
        .join(subject)
        .join("subject.json");
    let original_subject = fs::read(&subject_path).unwrap();

    fs::write(fixture.root.join("src/new.rs"), "new scoped source\n").unwrap();
    fs::remove_file(&tracked).unwrap();
    failure(
        fixture.run(&[
            "recover",
            "--root",
            fixture.root.to_str().unwrap(),
            "--json",
        ]),
        3,
        "conflict",
    );
    assert!(journal.exists());
    assert_eq!(fs::read(&plan).unwrap(), original_plan);

    fs::remove_file(fixture.root.join("src/new.rs")).unwrap();
    fs::write(&tracked, "baseline\n").unwrap();
    let mut metadata_only_change = original_subject.clone();
    metadata_only_change.push(b'\n');
    fs::write(&subject_path, metadata_only_change).unwrap();
    failure(
        fixture.run(&[
            "recover",
            "--root",
            fixture.root.to_str().unwrap(),
            "--json",
        ]),
        3,
        "conflict",
    );
    assert!(journal.exists());
    assert_eq!(fs::read(&plan).unwrap(), original_plan);

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        let original_mode = fs::metadata(&plan).unwrap().permissions().mode();
        fs::set_permissions(&plan, fs::Permissions::from_mode(0o600)).unwrap();
        failure(
            fixture.run(&[
                "recover",
                "--root",
                fixture.root.to_str().unwrap(),
                "--json",
            ]),
            3,
            "conflict",
        );
        assert!(journal.exists());
        fs::set_permissions(&plan, fs::Permissions::from_mode(original_mode)).unwrap();

        let same_bytes_target = fixture.root.join("same-bytes.md");
        fs::write(&same_bytes_target, &original_plan).unwrap();
        fs::remove_file(&plan).unwrap();
        std::os::unix::fs::symlink(&same_bytes_target, &plan).unwrap();
        failure(
            fixture.run(&[
                "recover",
                "--root",
                fixture.root.to_str().unwrap(),
                "--json",
            ]),
            3,
            "conflict",
        );
        assert!(journal.exists());
        fs::remove_file(&plan).unwrap();
        fs::write(&plan, &original_plan).unwrap();
        fs::set_permissions(&plan, fs::Permissions::from_mode(original_mode)).unwrap();
    }

    fs::write(&subject_path, original_subject).unwrap();
    let recovered = fixture.run(&[
        "recover",
        "--root",
        fixture.root.to_str().unwrap(),
        "--json",
    ]);
    assert!(
        recovered.status.success(),
        "{}",
        String::from_utf8_lossy(&recovered.stderr)
    );
    assert!(
        fs::read_to_string(&plan)
            .unwrap()
            .contains("status: active")
    );
    assert!(!journal.exists());
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
#[cfg(unix)]
fn prerequisite_conflicts_reject_same_bytes_symlink_for_an_applied_target() {
    let fixture = Fixture::new("applied-target-type-conflict");
    let plan = fixture.plan();
    let plan_text = fs::read_to_string(&plan).unwrap().replace("- [ ]", "- [x]");
    fs::write(&plan, plan_text).unwrap();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    fixture.approve(subject, "pre-edit", false);

    let interrupted = Command::new(common::bin())
        .args(["conclude", plan.to_str().unwrap(), "--json"])
        .current_dir(&fixture.root)
        .env("VARDE_CONFIG_DIR", &fixture.config)
        .env("VARDE_WORKFLOW_FAIL_CONCLUSION_AFTER_RENAMES", "1")
        .output()
        .unwrap();
    assert_eq!(interrupted.status.code(), Some(1));
    let journal = fixture.root.join(".varde-workflow-conclusion.json");
    assert!(journal.exists());
    let staged_plan = fs::read(&plan).unwrap();
    assert!(String::from_utf8_lossy(&staged_plan).contains("status: completed"));

    let same_bytes_target = fixture.root.join("same-completed-plan.md");
    fs::write(&same_bytes_target, &staged_plan).unwrap();
    fs::remove_file(&plan).unwrap();
    std::os::unix::fs::symlink(&same_bytes_target, &plan).unwrap();
    failure(
        fixture.run(&[
            "recover",
            "--root",
            fixture.root.to_str().unwrap(),
            "--json",
        ]),
        3,
        "conflict",
    );
    assert!(journal.exists());

    fs::remove_file(&plan).unwrap();
    fs::write(&plan, &staged_plan).unwrap();
    let recovered = fixture.run(&[
        "recover",
        "--root",
        fixture.root.to_str().unwrap(),
        "--json",
    ]);
    assert!(
        recovered.status.success(),
        "{}",
        String::from_utf8_lossy(&recovered.stderr)
    );
    assert!(
        fs::read_to_string(&plan)
            .unwrap()
            .contains("status: completed")
    );
    assert!(!journal.exists());
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn compatibility_preserves_completed_history_and_custom_workflow_types() {
    let fixture = Fixture::new("compatibility");
    let completed = fixture.plan();
    let completed_bytes = fs::read(&completed).unwrap();
    let historical = String::from_utf8(completed_bytes)
        .unwrap()
        .replace("status: backlog", "status: completed");
    fs::write(&completed, &historical).unwrap();
    let no_op = fixture.run(&["conclude", completed.to_str().unwrap(), "--json"]);
    assert!(
        no_op.status.success(),
        "{}",
        String::from_utf8_lossy(&no_op.stderr)
    );
    assert_eq!(common::json_data(&no_op.stdout)["already_completed"], true);
    assert_eq!(fs::read_to_string(&completed).unwrap(), historical);

    let schema = fixture
        .root
        .join("memory-bank/knowledge/workflow/schema.yml");
    fs::create_dir_all(schema.parent().unwrap()).unwrap();
    fs::write(
        &schema,
        "schema_version: 1\nartifact_types:\n  proposal:\n    initial_state: draft\n    states: [draft, published]\n    completion_states: [published]\n    transitions:\n      draft: [published]\n      published: []\n",
    )
    .unwrap();
    let custom = fixture.root.join("proposal.md");
    fs::write(&custom, "---\ntype: proposal\nstatus: draft\n---\nbody\n").unwrap();
    let transitioned = fixture.run(&[
        "transition",
        custom.to_str().unwrap(),
        "published",
        "--json",
    ]);
    assert!(
        transitioned.status.success(),
        "{}",
        String::from_utf8_lossy(&transitioned.stderr)
    );
    assert!(
        fs::read_to_string(&custom)
            .unwrap()
            .contains("status: published")
    );
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn path_identity_uses_linked_worktree_and_rejects_main_checkout_mismatch() {
    let fixture = Fixture::new("path-identity");
    fixture.git_init();
    fs::create_dir_all(fixture.root.join("src")).unwrap();
    fs::write(fixture.root.join("src/feature.rs"), "baseline\n").unwrap();
    fixture.plan();
    fixture.git_commit(&[
        "src/feature.rs",
        "memory-bank/working/plans/example/plan.md",
    ]);
    let linked = fixture.root.with_extension("linked-worktree");
    let added = Command::new("git")
        .args(["worktree", "add", "--detach", "-q"])
        .arg(&linked)
        .arg("HEAD")
        .current_dir(&fixture.root)
        .status()
        .unwrap();
    assert!(added.success());

    let shared_working = fixture.root.with_extension("shared-working");
    let shared_knowledge = fixture.root.with_extension("shared-knowledge");
    fs::write(
        fixture.config.join("config.toml"),
        format!(
            "[default]\nworking = \"{}\"\nknowledge = \"{}\"\n",
            shared_working.display(),
            shared_knowledge.display(),
        ),
    )
    .unwrap();
    let linked_plan = linked.join("memory-bank/working/plans/example/plan.md");
    let linked_created = fixture.run_at(
        &linked,
        &[
            "review",
            "init",
            "--plan",
            linked_plan.to_str().unwrap(),
            "--repository",
            linked.to_str().unwrap(),
            "--scope",
            "src",
            "--json",
        ],
    );
    let subject = success(linked_created)["subject"]["subject_id"]
        .as_str()
        .unwrap()
        .to_string();
    let nested = linked.join("nested");
    fs::create_dir_all(&nested).unwrap();
    let inspection = success(fixture.run_at(
        &nested,
        &[
            "review",
            "inspect",
            "--subject",
            &subject,
            "--phase",
            "pre-edit",
            "--json",
        ],
    ));
    let record_path = shared_working.join("review-record.json");
    let record = json!({
        "schema_version": 1,
        "subject_id": subject,
        "phase": "pre-edit",
        "reviewer": { "identity": "linked-reviewer", "provenance": "integration-test" },
        "verdict": "approved",
        "unresolved_choices": [],
        "contract_fingerprint": inspection["contract_fingerprint"],
        "baseline_id": inspection["baseline_id"],
        "verification_approach": "Run the linked-worktree CLI case.",
        "verification_rationale": "It checks actual worktree identity.",
        "verification_expected_results": "The linked subject is inspectable and can start.",
        "structural_risk": "low",
        "structural_risk_rationale": "The fixture changes one isolated plan.",
        "implementation_review_required": false,
        "rationale": "The reviewed transition has no unresolved choices."
    });
    fs::write(&record_path, serde_json::to_vec_pretty(&record).unwrap()).unwrap();
    success(fixture.run_at(
        &nested,
        &[
            "review",
            "record",
            "--subject",
            &subject,
            "--expected-version",
            inspection["version"].as_str().unwrap(),
            "--file",
            record_path.to_str().unwrap(),
            "--json",
        ],
    ));
    let started = fixture.run_at(
        &nested,
        &[
            "transition",
            linked_plan.to_str().unwrap(),
            "active",
            "--json",
        ],
    );
    assert!(
        started.status.success(),
        "{}",
        String::from_utf8_lossy(&started.stderr)
    );

    failure(
        fixture.run(&[
            "review",
            "inspect",
            "--subject",
            &subject,
            "--phase",
            "pre-edit",
            "--json",
        ]),
        4,
        "review_invalid",
    );
    let _ = Command::new("git")
        .args(["worktree", "remove", "--force"])
        .arg(&linked)
        .current_dir(&fixture.root)
        .status();
    fs::remove_dir_all(&shared_working).unwrap();
    let _ = fs::remove_dir_all(&shared_knowledge);
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn blocked_verdict_can_report_an_implementation_failure_without_a_human_choice() {
    let fixture = Fixture::new("blocked-no-choice");
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    let inspection = fixture.inspect(subject, "pre-edit");
    let record_path = fixture.root.join("blocked.json");
    let record = json!({
        "schema_version": 1,
        "subject_id": subject,
        "phase": "pre-edit",
        "reviewer": { "identity": "independent-reviewer", "provenance": "local-agent" },
        "verdict": "blocked",
        "unresolved_choices": [],
        "contract_fingerprint": inspection["contract_fingerprint"],
        "baseline_id": inspection["baseline_id"],
        "verification_approach": "Run the failing focused case.",
        "verification_rationale": "The implementation failure blocks approval.",
        "verification_expected_results": "The regression reproduces before a fix.",
        "structural_risk": "low",
        "structural_risk_rationale": "Only a local implementation failure is under review.",
        "implementation_review_required": false,
        "rationale": "The review found a code failure but no human decision."
    });
    fs::write(&record_path, serde_json::to_vec_pretty(&record).unwrap()).unwrap();
    success(fixture.run(&[
        "review",
        "record",
        "--subject",
        subject,
        "--expected-version",
        inspection["version"].as_str().unwrap(),
        "--file",
        record_path.to_str().unwrap(),
        "--json",
    ]));
    failure(
        fixture.run(&[
            "review",
            "check",
            "--subject",
            subject,
            "--checkpoint",
            "start",
            "--json",
        ]),
        4,
        "review_blocked",
    );
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn contract_freshness_ignores_bookkeeping_and_detects_material_edits() {
    let fixture = Fixture::new("contract-freshness");
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    let inspection = fixture.inspect(subject, "pre-edit");
    success(fixture.record_approved(subject, "pre-edit", &inspection));
    success(fixture.run(&[
        "review",
        "check",
        "--subject",
        subject,
        "--checkpoint",
        "start",
        "--json",
    ]));

    let original = fs::read_to_string(&plan).unwrap();
    let bookkeeping = original
        .replace("status: backlog", "status: active")
        .replace("- [ ] The behavior works.", "- [x] The behavior works.")
        .replace("- started", "- more progress")
        .replace("The original problem.", "The original\nproblem.");
    fs::write(&plan, bookkeeping).unwrap();
    success(fixture.run(&[
        "review",
        "check",
        "--subject",
        subject,
        "--checkpoint",
        "resume",
        "--json",
    ]));

    fs::write(
        &plan,
        fs::read_to_string(&plan)
            .unwrap()
            .replace("Implement the solution.", "Replace the solution."),
    )
    .unwrap();
    let stale = failure(
        fixture.run(&[
            "review",
            "check",
            "--subject",
            subject,
            "--checkpoint",
            "resume",
            "--json",
        ]),
        4,
        "review_stale_contract",
    );
    assert_eq!(
        stale["data"]["error"]["details"]["blockers"][0]["code"],
        "review_stale_contract"
    );
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn bounded_contract_update_changes_normalized_fingerprint() {
    let fixture = Fixture::new("bounded-contract");
    let source = fixture.root.join("contract.json");
    fs::write(
        &source,
        serde_json::to_vec(&json!({
            "outcome": "Provide bounded checks",
            "scope": ["src"],
            "assumptions": [],
            "design": "Use the current path",
            "verification": "Run focused test",
            "open_questions": []
        }))
        .unwrap(),
    )
    .unwrap();
    let output = fixture.run(&[
        "review",
        "init",
        "--subject",
        "bounded-example",
        "--contract",
        source.to_str().unwrap(),
        "--repository",
        fixture.root.to_str().unwrap(),
        "--scope",
        "src",
        "--json",
    ]);
    let created = success(output);
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    let inspection = fixture.inspect(subject, "pre-edit");
    let old_fingerprint = inspection["contract_fingerprint"].clone();

    fs::write(
        &source,
        serde_json::to_vec(&json!({
            "outcome": "Provide bounded checks",
            "scope": ["src"],
            "assumptions": [],
            "design": "Use the reviewed current path",
            "verification": "Run focused test",
            "open_questions": []
        }))
        .unwrap(),
    )
    .unwrap();
    success(fixture.run(&[
        "review",
        "contract",
        "--subject",
        subject,
        "--expected-version",
        inspection["version"].as_str().unwrap(),
        "--file",
        source.to_str().unwrap(),
        "--json",
    ]));
    let updated = fixture.inspect(subject, "pre-edit");
    assert_ne!(updated["contract_fingerprint"], old_fingerprint);

    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn scope_expansion_is_monotonic_and_changes_baseline_identity() {
    let fixture = Fixture::new("scope-expansion");
    fs::create_dir_all(fixture.root.join("src")).unwrap();
    fs::create_dir_all(fixture.root.join("docs")).unwrap();
    fs::write(fixture.root.join("src/lib.rs"), "pub fn value() {}\n").unwrap();
    fs::write(fixture.root.join("docs/design.md"), "current docs\n").unwrap();
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    let initial = fixture.inspect(subject, "pre-edit");
    success(fixture.record_approved(subject, "pre-edit", &initial));
    let before = fixture.inspect(subject, "pre-edit");

    success(fixture.run(&[
        "review",
        "expand",
        "--subject",
        subject,
        "--expected-version",
        before["version"].as_str().unwrap(),
        "--scope",
        "docs",
        "--json",
    ]));
    let after = fixture.inspect(subject, "pre-edit");
    assert_ne!(after["baseline_id"], before["baseline_id"]);
    assert_eq!(after["subject"]["scope"], json!(["docs", "src"]));
    let docs_entry = after["manifest"]["entries"]
        .as_array()
        .unwrap()
        .iter()
        .find(|entry| entry["path"] == "docs/design.md")
        .unwrap();
    assert_eq!(
        docs_entry["baseline"]["sha1"],
        docs_entry["current"]["sha1"]
    );
    failure(
        fixture.run(&[
            "review",
            "check",
            "--subject",
            subject,
            "--checkpoint",
            "start",
            "--json",
        ]),
        4,
        "review_stale_contract",
    );

    let stale_version = failure(
        fixture.run(&[
            "review",
            "expand",
            "--subject",
            subject,
            "--expected-version",
            before["version"].as_str().unwrap(),
            "--scope",
            "elsewhere",
            "--json",
        ]),
        3,
        "conflict",
    );
    assert_eq!(stale_version["data"]["error"]["code"], "conflict");
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn git_coverage_manifest_tracks_edits_additions_deletions_renames_modes_and_symlinks() {
    let fixture = Fixture::new("git-coverage");
    fixture.git_init();
    fs::create_dir_all(fixture.root.join("src")).unwrap();
    fs::write(fixture.root.join("src/changed.rs"), "before\n").unwrap();
    fs::write(fixture.root.join("src/deleted.rs"), "deleted\n").unwrap();
    fs::write(fixture.root.join("src/old-name.rs"), "rename\n").unwrap();
    fs::write(
        fixture.root.join("src/untracked-at-baseline.rs"),
        "initial dirty state\n",
    )
    .unwrap();
    fs::write(
        fixture.root.join("ignored.out"),
        "explicitly scoped ignored file\n",
    )
    .unwrap();
    fs::write(fixture.root.join(".gitignore"), "ignored.out\n").unwrap();
    fixture.git_commit(&[
        "src/changed.rs",
        "src/deleted.rs",
        "src/old-name.rs",
        ".gitignore",
    ]);
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();

    fs::write(fixture.root.join("src/changed.rs"), "after\n").unwrap();
    fs::remove_file(fixture.root.join("src/deleted.rs")).unwrap();
    fs::rename(
        fixture.root.join("src/old-name.rs"),
        fixture.root.join("src/new-name.rs"),
    )
    .unwrap();
    fs::write(fixture.root.join("src/added.rs"), "added after baseline\n").unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode_file = fixture.root.join("src/changed.rs");
        fs::set_permissions(&mode_file, fs::Permissions::from_mode(0o755)).unwrap();
        std::os::unix::fs::symlink("changed.rs", fixture.root.join("src/link.rs")).unwrap();
    }
    let after = fixture.inspect(subject, "pre-edit");
    let entries = after["manifest"]["entries"].as_array().unwrap();
    let changed = entries
        .iter()
        .find(|entry| entry["path"] == "src/changed.rs")
        .unwrap();
    assert_eq!(changed["change"], "modified");
    assert_ne!(changed["baseline"]["mode"], changed["current"]["mode"]);
    assert!(
        entries
            .iter()
            .any(|entry| entry["path"] == "src/added.rs" && entry["change"] == "added")
    );
    assert!(
        entries
            .iter()
            .any(|entry| entry["path"] == "src/deleted.rs" && entry["change"] == "deleted")
    );
    assert!(
        entries
            .iter()
            .any(|entry| entry["path"] == "src/old-name.rs" && entry["change"] == "deleted")
    );
    assert!(
        entries
            .iter()
            .any(|entry| entry["path"] == "src/new-name.rs" && entry["change"] == "added")
    );
    assert!(
        entries
            .iter()
            .any(|entry| entry["path"] == "src/untracked-at-baseline.rs"
                && entry["change"] == "unchanged")
    );
    #[cfg(unix)]
    assert!(
        entries
            .iter()
            .any(|entry| entry["path"] == "src/link.rs" && entry["current"]["type"] == "symlink")
    );

    let explicitly_named = fixture.run(&[
        "review",
        "expand",
        "--subject",
        subject,
        "--expected-version",
        after["version"].as_str().unwrap(),
        "--scope",
        "ignored.out",
        "--json",
    ]);
    success(explicitly_named);
    let expanded = fixture.inspect(subject, "pre-edit");
    assert!(
        expanded["manifest"]["entries"]
            .as_array()
            .unwrap()
            .iter()
            .any(|entry| entry["path"] == "ignored.out")
    );
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn record_uses_inspection_revision_for_occ() {
    let fixture = Fixture::new("record-occ");
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    let inspection = fixture.inspect(subject, "pre-edit");
    success(fixture.record_approved(subject, "pre-edit", &inspection));
    failure(
        fixture.record_approved(subject, "pre-edit", &inspection),
        3,
        "conflict",
    );
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn non_git_inventory_and_retrievable_immutable_baseline_are_reported() {
    let fixture = Fixture::new("non-git");
    fs::create_dir_all(fixture.root.join("src")).unwrap();
    fs::write(fixture.root.join("src/lib.rs"), "before\n").unwrap();
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    let baseline = fixture.inspect(subject, "pre-edit");
    fs::write(fixture.root.join("src/lib.rs"), "after\n").unwrap();
    let current = fixture.inspect(subject, "pre-edit");
    let entry = current["manifest"]["entries"]
        .as_array()
        .unwrap()
        .iter()
        .find(|entry| entry["path"] == "src/lib.rs")
        .unwrap();
    assert_eq!(entry["change"], "modified");
    assert_ne!(entry["baseline"]["sha1"], entry["current"]["sha1"]);
    let baseline_path = PathBuf::from(entry["baseline"]["content_path"].as_str().unwrap());
    assert!(baseline_path.is_file());
    assert_eq!(fs::read(baseline_path).unwrap(), b"before\n");
    assert_eq!(baseline["baseline_id"], current["baseline_id"]);
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn git_repository_root_scope_does_not_treat_the_root_as_a_submodule() {
    let fixture = Fixture::new("git-root-scope");
    fixture.git_init();
    fs::create_dir_all(fixture.root.join("src")).unwrap();
    fs::write(fixture.root.join("src/lib.rs"), "root scoped file\n").unwrap();
    fixture.git_commit(&["src/lib.rs"]);
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, ".");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    let inspection = fixture.inspect(subject, "pre-edit");
    assert!(
        inspection["manifest"]["entries"]
            .as_array()
            .unwrap()
            .iter()
            .any(|entry| entry["path"] == "src/lib.rs")
    );
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn tracked_dirty_baseline_survives_later_commits_without_resetting_coverage() {
    let fixture = Fixture::new("git-committed-change");
    fixture.git_init();
    fs::create_dir_all(fixture.root.join("src")).unwrap();
    fs::write(
        fixture.root.join(".gitignore"),
        "memory-bank/working/\n.varde-workflow.lock\n",
    )
    .unwrap();
    fs::write(fixture.root.join("src/tracked.rs"), "committed version\n").unwrap();
    fixture.git_commit(&[".gitignore", "src/tracked.rs"]);

    fs::write(
        fixture.root.join("src/tracked.rs"),
        "dirty before baseline\n",
    )
    .unwrap();
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    let baseline_id = created["baseline_id"].as_str().unwrap();
    let entry = created["manifest"]["entries"]
        .as_array()
        .unwrap()
        .iter()
        .find(|entry| entry["path"] == "src/tracked.rs")
        .unwrap();
    assert_eq!(entry["change"], "unchanged");
    let blob = PathBuf::from(entry["baseline"]["content_path"].as_str().unwrap());
    assert_eq!(fs::read(blob).unwrap(), b"dirty before baseline\n");

    fs::write(fixture.root.join("src/tracked.rs"), "implementation edit\n").unwrap();
    let before_commit = fixture.inspect(subject, "pre-edit");
    let change_fingerprint = before_commit["change_fingerprint"].as_str().unwrap();
    assert!(
        before_commit["manifest"]["entries"]
            .as_array()
            .unwrap()
            .iter()
            .any(|entry| entry["path"] == "src/tracked.rs" && entry["change"] == "modified")
    );

    fixture.git_commit(&["src/tracked.rs"]);
    let after_commit = fixture.inspect(subject, "pre-edit");
    assert_eq!(after_commit["baseline_id"], baseline_id);
    assert_eq!(after_commit["change_fingerprint"], change_fingerprint);
    assert!(
        after_commit["manifest"]["entries"]
            .as_array()
            .unwrap()
            .iter()
            .any(|entry| entry["path"] == "src/tracked.rs" && entry["change"] == "modified")
    );
    let status = Command::new("git")
        .args(["status", "--porcelain"])
        .current_dir(&fixture.root)
        .output()
        .unwrap();
    assert!(status.status.success());
    assert!(status.stdout.is_empty());
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn non_git_root_scope_excludes_only_exact_generated_workflow_names() {
    let fixture = Fixture::new("non-git-generated");
    fs::write(fixture.root.join("user.varde-stage-42"), "user file\n").unwrap();
    fs::write(
        fixture.root.join("user.md.varde-stage-42"),
        "generated stage\n",
    )
    .unwrap();
    fs::write(fixture.root.join(".varde-workflow.lock"), "lock\n").unwrap();
    fs::write(
        fixture.root.join(".varde-workflow-journal.json"),
        "journal\n",
    )
    .unwrap();
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, ".");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    let inspection = fixture.inspect(subject, "pre-edit");
    let paths: Vec<&str> = inspection["manifest"]["entries"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|entry| entry["path"].as_str())
        .collect();
    assert!(paths.contains(&"user.varde-stage-42"));
    assert!(!paths.contains(&"user.md.varde-stage-42"));
    assert!(!paths.contains(&".varde-workflow.lock"));
    assert!(!paths.contains(&".varde-workflow-journal.json"));
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn unknown_subject_and_unsupported_stored_schema_fail_closed_with_json() {
    let fixture = Fixture::new("invalid-schema");
    failure(
        fixture.run(&[
            "review",
            "check",
            "--subject",
            "unknown-subject",
            "--checkpoint",
            "start",
            "--json",
        ]),
        4,
        "review_missing",
    );

    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    let subject_path = fixture
        .root
        .join("memory-bank/working/review-gates")
        .join(subject)
        .join("subject.json");
    let inspection = fixture.inspect(subject, "pre-edit");
    success(fixture.record_approved(subject, "pre-edit", &inspection));
    let record_path = subject_path.parent().unwrap().join("pre-edit.json");
    let mut record: Value = serde_json::from_slice(&fs::read(&record_path).unwrap()).unwrap();
    record["schema_version"] = json!(99);
    fs::write(&record_path, serde_json::to_vec_pretty(&record).unwrap()).unwrap();
    failure(
        fixture.run(&[
            "review",
            "check",
            "--subject",
            subject,
            "--checkpoint",
            "start",
            "--json",
        ]),
        4,
        "review_invalid",
    );

    let mut stored: Value = serde_json::from_slice(&fs::read(&subject_path).unwrap()).unwrap();
    stored["schema_version"] = json!(99);
    fs::write(&subject_path, serde_json::to_vec_pretty(&stored).unwrap()).unwrap();
    failure(
        fixture.run(&[
            "review",
            "check",
            "--subject",
            subject,
            "--checkpoint",
            "start",
            "--json",
        ]),
        4,
        "review_invalid",
    );
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn required_implementation_record_covers_the_whole_current_manifest() {
    let fixture = Fixture::new("implementation-record");
    let plan = fixture.plan();
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    let inspection = fixture.inspect(subject, "pre-edit");
    let record_path = fixture.root.join("pre-edit-record.json");
    let mut record = json!({
        "schema_version": 1,
        "subject_id": subject,
        "phase": "pre-edit",
        "reviewer": { "identity": "independent-reviewer", "provenance": "local-agent" },
        "verdict": "approved",
        "unresolved_choices": [],
        "contract_fingerprint": inspection["contract_fingerprint"],
        "baseline_id": inspection["baseline_id"],
        "verification_approach": "Run the scoped tests.",
        "verification_rationale": "They cover the expected file change.",
        "verification_expected_results": "The change fingerprint tracks every scoped path.",
        "structural_risk": "high",
        "structural_risk_rationale": "The change affects a shared contract.",
        "implementation_review_required": true,
        "rationale": "The plan is clear and reviewable."
    });
    fs::write(&record_path, serde_json::to_vec_pretty(&record).unwrap()).unwrap();
    success(fixture.run(&[
        "review",
        "record",
        "--subject",
        subject,
        "--expected-version",
        inspection["version"].as_str().unwrap(),
        "--file",
        record_path.to_str().unwrap(),
        "--json",
    ]));

    fs::create_dir_all(fixture.root.join("src")).unwrap();
    fs::write(fixture.root.join("src/change.rs"), "first implementation\n").unwrap();
    let implementation = fixture.inspect(subject, "implementation");
    record = json!({
        "schema_version": 1,
        "subject_id": subject,
        "phase": "implementation",
        "reviewer": { "identity": "independent-reviewer", "provenance": "local-agent" },
        "verdict": "approved",
        "unresolved_choices": [],
        "contract_fingerprint": implementation["contract_fingerprint"],
        "baseline_id": implementation["baseline_id"],
        "change_fingerprint": implementation["change_fingerprint"],
        "coverage": "entire-subject-change",
        "verification_approach": "Run the scoped tests.",
        "verification_rationale": "They exercise the completed change.",
        "verification_expected_results": "The complete manifest passes review.",
        "rationale": "The entire subject change is covered."
    });
    fs::write(&record_path, serde_json::to_vec_pretty(&record).unwrap()).unwrap();
    success(fixture.run(&[
        "review",
        "record",
        "--subject",
        subject,
        "--expected-version",
        implementation["version"].as_str().unwrap(),
        "--file",
        record_path.to_str().unwrap(),
        "--json",
    ]));
    success(fixture.run(&[
        "review",
        "check",
        "--subject",
        subject,
        "--checkpoint",
        "complete",
        "--json",
    ]));

    fs::write(
        fixture.root.join("src/change.rs"),
        "later unreviewed edit\n",
    )
    .unwrap();
    failure(
        fixture.run(&[
            "review",
            "check",
            "--subject",
            subject,
            "--checkpoint",
            "complete",
            "--json",
        ]),
        4,
        "review_stale_changes",
    );
    fs::remove_dir_all(fixture.root).unwrap();
}

#[test]
fn explicit_worktree_binding_allows_only_scoped_inherited_approval() {
    let fixture = Fixture::new("binding");
    fixture.git_init();
    fs::create_dir_all(fixture.root.join("src")).unwrap();
    fs::write(fixture.root.join("src/feature.rs"), "baseline\n").unwrap();
    let plan = fixture.plan();
    fixture.git_commit(&["src", "memory-bank"]);
    let created = fixture.init_plan(&plan, "src");
    let subject = created["subject"]["subject_id"].as_str().unwrap();
    fixture.approve(subject, "pre-edit", true);
    success(fixture.transition(&plan, "active"));
    let linked = fixture.root.with_extension("bound-linked");
    assert!(
        Command::new("git")
            .args(["worktree", "add", "-qb", "worker"])
            .arg(&linked)
            .current_dir(&fixture.root)
            .status()
            .unwrap()
            .success()
    );
    let inspection = fixture.inspect(subject, "pre-edit");
    success(fixture.run(&[
        "review",
        "bind-worktree",
        "--subject",
        subject,
        "--binding",
        "worker",
        "--expected-version",
        inspection["version"].as_str().unwrap(),
        "--worktree",
        linked.to_str().unwrap(),
        "--scope",
        "src/feature.rs",
        "--json",
    ]));
    success(fixture.run_at(
        &linked,
        &[
            "review",
            "check",
            "--subject",
            subject,
            "--repository",
            fixture.root.to_str().unwrap(),
            "--worktree",
            linked.to_str().unwrap(),
            "--binding",
            "worker",
            "--checkpoint",
            "start",
            "--json",
        ],
    ));
    failure(
        fixture.run(&[
            "review",
            "check",
            "--subject",
            subject,
            "--checkpoint",
            "complete",
            "--json",
        ]),
        4,
        "review_blocked",
    );
    fs::write(linked.join("other.rs"), "stray\n").unwrap();
    failure(
        fixture.run_at(
            &linked,
            &[
                "review",
                "check",
                "--subject",
                subject,
                "--repository",
                fixture.root.to_str().unwrap(),
                "--worktree",
                linked.to_str().unwrap(),
                "--binding",
                "worker",
                "--checkpoint",
                "resume",
                "--json",
            ],
        ),
        4,
        "review_invalid",
    );
    fs::remove_file(linked.join("other.rs")).unwrap();
    assert!(
        Command::new("git")
            .args(["worktree", "remove", "--force"])
            .arg(&linked)
            .current_dir(&fixture.root)
            .status()
            .unwrap()
            .success()
    );
}

struct WorktreeFixture {
    fixture: Fixture,
    subject: String,
    worker: PathBuf,
}
impl WorktreeFixture {
    fn new(tag: &str) -> Self {
        let fixture = Fixture::new(tag);
        fixture.git_init();
        fs::create_dir_all(fixture.root.join("src")).unwrap();
        fs::write(fixture.root.join("src/a.rs"), "baseline\n").unwrap();
        fs::write(fixture.root.join("src/b.rs"), "other\n").unwrap();
        let plan = fixture.plan();
        fixture.git_commit(&["src", "memory-bank"]);
        let created = fixture.init_plan(&plan, "src");
        let subject = created["subject"]["subject_id"]
            .as_str()
            .unwrap()
            .to_owned();
        fixture.approve(&subject, "pre-edit", true);
        success(fixture.transition(&plan, "active"));
        let worker = fixture.root.with_extension(format!("{tag}-worker"));
        let _ = fs::remove_dir_all(&worker);
        assert!(
            Command::new("git")
                .args(["worktree", "add", "-qb", "worker"])
                .arg(&worker)
                .current_dir(&fixture.root)
                .status()
                .unwrap()
                .success()
        );
        Self {
            fixture,
            subject,
            worker,
        }
    }
    fn bind(&self, scope: &str) -> Value {
        let inspected = self.fixture.inspect(&self.subject, "pre-edit");
        success(self.fixture.run(&[
            "review",
            "bind-worktree",
            "--subject",
            &self.subject,
            "--binding",
            "worker",
            "--expected-version",
            inspected["version"].as_str().unwrap(),
            "--worktree",
            self.worker.to_str().unwrap(),
            "--scope",
            scope,
            "--json",
        ]))
    }
    fn inspect(&self) -> Value {
        success(self.fixture.run(&[
            "review",
            "inspect-worktree",
            "--subject",
            &self.subject,
            "--binding",
            "worker",
            "--json",
        ]))
    }
    fn check(&self, checkpoint: &str) -> Output {
        self.fixture.run_at(
            &self.worker,
            &[
                "review",
                "check",
                "--subject",
                &self.subject,
                "--repository",
                self.fixture.root.to_str().unwrap(),
                "--worktree",
                self.worker.to_str().unwrap(),
                "--binding",
                "worker",
                "--checkpoint",
                checkpoint,
                "--json",
            ],
        )
    }
    fn git_worker(&self, args: &[&str]) -> String {
        let output = Command::new("git")
            .args(args)
            .current_dir(&self.worker)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        String::from_utf8(output.stdout).unwrap().trim().to_owned()
    }
    fn release(&self, version: &str, commit: &str) -> Output {
        self.fixture.run(&[
            "review",
            "release-worktree",
            "--subject",
            &self.subject,
            "--binding",
            "worker",
            "--expected-version",
            version,
            "--commit",
            commit,
            "--json",
        ])
    }
}
impl Drop for WorktreeFixture {
    fn drop(&mut self) {
        let _ = Command::new("git")
            .args(["worktree", "remove", "--force"])
            .arg(&self.worker)
            .current_dir(&self.fixture.root)
            .output();
    }
}

#[test]
fn binding_release_requires_integration_and_final_review_survives_cleanup() {
    let case = WorktreeFixture::new("binding-release");
    case.bind("src/a.rs");
    fs::write(case.worker.join("src/a.rs"), "changed\n").unwrap();
    case.git_worker(&["add", "src/a.rs"]);
    case.git_worker(&["commit", "-qm", "scoped worker"]);
    let commit = case.git_worker(&["rev-parse", "HEAD"]);
    let before = case.inspect();
    failure(
        case.release(before["version"].as_str().unwrap(), &commit),
        4,
        "review_invalid",
    );
    assert!(
        Command::new("git")
            .args(["merge", "--ff-only", "worker"])
            .current_dir(&case.fixture.root)
            .output()
            .unwrap()
            .status
            .success()
    );
    let integrated = case.inspect();
    failure(
        case.release(before["version"].as_str().unwrap(), &commit),
        3,
        "conflict",
    );
    success(case.release(integrated["version"].as_str().unwrap(), &commit));
    failure(case.check("resume"), 4, "review_invalid");
    assert!(
        Command::new("git")
            .args(["worktree", "remove"])
            .arg(&case.worker)
            .current_dir(&case.fixture.root)
            .output()
            .unwrap()
            .status
            .success()
    );
    assert_eq!(case.inspect()["state"], "released");
    case.fixture.approve(&case.subject, "implementation", true);
    success(case.fixture.run(&[
        "review",
        "check",
        "--subject",
        &case.subject,
        "--checkpoint",
        "complete",
        "--json",
    ]));
    fs::write(case.fixture.root.join("src/b.rs"), "later source\n").unwrap();
    failure(
        case.fixture.run(&[
            "review",
            "check",
            "--subject",
            &case.subject,
            "--checkpoint",
            "complete",
            "--json",
        ]),
        4,
        "review_stale_changes",
    );
}

#[test]
fn binding_rejects_stale_parent_committed_scope_escape_and_wrong_branch() {
    let case = WorktreeFixture::new("binding-drift");
    case.bind("src/a.rs");
    fs::write(case.worker.join("src/b.rs"), "stray committed\n").unwrap();
    case.git_worker(&["add", "src/b.rs"]);
    case.git_worker(&["commit", "-qm", "stray"]);
    failure(case.check("resume"), 4, "review_invalid");
    case.git_worker(&["reset", "--hard", "HEAD~1"]);
    case.git_worker(&["checkout", "-qb", "other-branch"]);
    failure(case.check("start"), 4, "review_invalid");
    case.git_worker(&["checkout", "worker"]);
    let plan = case
        .fixture
        .root
        .join("memory-bank/working/plans/example/plan.md");
    fs::write(
        &plan,
        fs::read_to_string(&plan).unwrap().replace(
            "Implement the solution.",
            "A materially different solution.",
        ),
    )
    .unwrap();
    failure(case.check("resume"), 4, "review_stale_contract");
    failure(case.check("complete"), 4, "review_invalid");
}

#[test]
fn bind_rejects_scope_expansion_clone_and_stale_occ_without_publication() {
    let case = WorktreeFixture::new("binding-reject");
    let inspection = case.fixture.inspect(&case.subject, "pre-edit");
    let args = |worktree: &Path, scope: &str, version: &str| {
        case.fixture.run(&[
            "review",
            "bind-worktree",
            "--subject",
            &case.subject,
            "--binding",
            "worker",
            "--expected-version",
            version,
            "--worktree",
            worktree.to_str().unwrap(),
            "--scope",
            scope,
            "--json",
        ])
    };
    failure(
        args(
            &case.worker,
            "outside.rs",
            inspection["version"].as_str().unwrap(),
        ),
        4,
        "review_invalid",
    );
    let clone = case.fixture.root.with_extension("unrelated-clone");
    assert!(
        Command::new("git")
            .args(["clone", "-q"])
            .arg(&case.fixture.root)
            .arg(&clone)
            .output()
            .unwrap()
            .status
            .success()
    );
    failure(
        args(&clone, "src/a.rs", inspection["version"].as_str().unwrap()),
        4,
        "review_invalid",
    );
    failure(args(&case.worker, "src/a.rs", "stale"), 3, "conflict");
    assert!(
        !case
            .fixture
            .root
            .join("memory-bank/working/review-gates")
            .join(&case.subject)
            .join("worktrees/worker")
            .exists()
    );
    let bound = case.bind("src/a.rs");
    assert_eq!(bound["binding"]["scope"], json!(["src/a.rs"]));
    let _ = fs::remove_dir_all(clone);
}

#[test]
fn task_binding_rejects_ownership_and_verification_drift_but_allows_progress() {
    let case = WorktreeFixture::new("binding-task");
    case.fixture.approve(&case.subject, "pre-edit", false);
    let task = case
        .fixture
        .root
        .join("memory-bank/working/plans/example/tasks/change.md");
    fs::create_dir_all(task.parent().unwrap()).unwrap();
    fs::write(&task,"---\ntype: task\nstatus: in_progress\nmodifies: [src/a.rs]\ncreates: []\nrenames: []\nverification_resources: []\n---\n\n#### Verification\n- assert: check -> pass\n\n#### Progress\n").unwrap();
    let inspection = case.fixture.inspect(&case.subject, "pre-edit");
    success(case.fixture.run(&[
        "review",
        "bind-worktree",
        "--subject",
        &case.subject,
        "--binding",
        "worker",
        "--expected-version",
        inspection["version"].as_str().unwrap(),
        "--worktree",
        case.worker.to_str().unwrap(),
        "--scope",
        "src/a.rs",
        "--task",
        task.to_str().unwrap(),
        "--json",
    ]));
    fs::write(
        &task,
        fs::read_to_string(&task)
            .unwrap()
            .replace("status: todo", "status: in_progress")
            + "- progress event\n",
    )
    .unwrap();
    success(case.check("resume"));
    fs::write(
        case.worker.join("src/a.rs"),
        "verified original task result\n",
    )
    .unwrap();
    case.git_worker(&["add", "src/a.rs"]);
    case.git_worker(&["commit", "-qm", "original task result"]);
    let commit = case.git_worker(&["rev-parse", "HEAD"]);
    fs::write(
        &task,
        fs::read_to_string(&task)
            .unwrap()
            .replace("assert: check -> pass", "assert: changed-check -> pass"),
    )
    .unwrap();
    failure(case.check("resume"), 4, "review_invalid");
    assert!(
        Command::new("git")
            .args(["merge", "--ff-only", "worker"])
            .current_dir(&case.fixture.root)
            .output()
            .unwrap()
            .status
            .success()
    );
    let stale_task_evidence = case.inspect();
    assert_eq!(stale_task_evidence["execution_ready"], false);
    success(case.release(stale_task_evidence["version"].as_str().unwrap(), &commit));
    failure(
        case.fixture.run(&[
            "review",
            "check",
            "--subject",
            &case.subject,
            "--checkpoint",
            "complete",
            "--json",
        ]),
        4,
        "review_missing",
    );
    case.fixture.approve(&case.subject, "implementation", false);
    success(case.fixture.run(&[
        "review",
        "check",
        "--subject",
        &case.subject,
        "--checkpoint",
        "complete",
        "--json",
    ]));
}

#[test]
fn binding_releases_committed_rename_and_rejects_hidden_or_newline_scope_escape() {
    let case = WorktreeFixture::new("binding-rename");
    case.bind("src");
    fs::create_dir_all(case.worker.join(".varde")).unwrap();
    fs::write(case.worker.join(".varde/config.json"), "hidden mutation").unwrap();
    failure(case.check("resume"), 4, "review_invalid");
    fs::remove_dir_all(case.worker.join(".varde")).unwrap();
    let worker_plan = case
        .worker
        .join("memory-bank/working/plans/example/plan.md");
    let original_plan = fs::read_to_string(&worker_plan).unwrap();
    fs::write(
        &worker_plan,
        original_plan.replace("The original problem.", "Unauthorized worker bookkeeping."),
    )
    .unwrap();
    case.git_worker(&["add", "memory-bank/working/plans/example/plan.md"]);
    case.git_worker(&["commit", "-qm", "unauthorized task bookkeeping"]);
    failure(case.check("resume"), 4, "review_invalid");
    case.git_worker(&["reset", "--hard", "HEAD~1"]);
    fs::write(case.worker.join("src/allowed\nstray.rs"), "new filename").unwrap();
    success(case.check("resume")); // Entire src directory is intentionally authorized.
    fs::remove_file(case.worker.join("src/allowed\nstray.rs")).unwrap();
    fs::write(case.worker.join("outside\nname.rs"), "scope escape").unwrap();
    failure(case.check("resume"), 4, "review_invalid");
    fs::remove_file(case.worker.join("outside\nname.rs")).unwrap();
    case.git_worker(&["mv", "src/a.rs", "src/renamed.rs"]);
    case.git_worker(&["rm", "src/b.rs"]);
    case.git_worker(&["commit", "-qm", "rename and deletion"]);
    let commit = case.git_worker(&["rev-parse", "HEAD"]);
    assert!(
        Command::new("git")
            .args(["merge", "--ff-only", "worker"])
            .current_dir(&case.fixture.root)
            .output()
            .unwrap()
            .status
            .success()
    );
    let evidence = case.inspect();
    success(case.release(evidence["version"].as_str().unwrap(), &commit));
}

#[test]
fn binding_rejects_blocked_task_and_blocked_parent_lifecycle() {
    let case = WorktreeFixture::new("binding-lifecycle");
    let task = case
        .fixture
        .root
        .join("memory-bank/working/plans/example/tasks/change.md");
    fs::create_dir_all(task.parent().unwrap()).unwrap();
    fs::write(&task,"---\ntype: task\nstatus: in_progress\ndepends_on: []\nmodifies: [src/a.rs]\ncreates: []\nrenames: []\nverification_resources: []\n---\n#### Verification\n- assert: check -> pass\n#### Progress\n").unwrap();
    let inspection = case.fixture.inspect(&case.subject, "pre-edit");
    success(case.fixture.run(&[
        "review",
        "bind-worktree",
        "--subject",
        &case.subject,
        "--binding",
        "worker",
        "--expected-version",
        inspection["version"].as_str().unwrap(),
        "--worktree",
        case.worker.to_str().unwrap(),
        "--scope",
        "src/a.rs",
        "--task",
        task.to_str().unwrap(),
        "--json",
    ]));
    let original = fs::read_to_string(&task).unwrap();
    fs::write(
        &task,
        original.replace("status: in_progress", "status: blocked"),
    )
    .unwrap();
    failure(case.check("resume"), 4, "review_invalid");
    fs::write(&task, &original).unwrap();
    fs::write(
        &task,
        original.replace("depends_on: []", "depends_on: [other-task]"),
    )
    .unwrap();
    failure(case.check("resume"), 4, "review_invalid");
    fs::write(&task, &original).unwrap();
    let plan = case
        .fixture
        .root
        .join("memory-bank/working/plans/example/plan.md");
    success(case.fixture.transition(&plan, "blocked"));
    failure(case.check("resume"), 4, "review_invalid");
}

#[test]
fn binding_rejects_parent_exclusion_and_symlink_escape() {
    let case = WorktreeFixture::new("binding-exclusions");
    // A second bounded subject permits testing explicit exclusions without
    // changing the existing immutable plan subject baseline.
    let contract = case.fixture.root.join("bounded.json");
    fs::write(&contract,serde_json::to_vec(&json!({"outcome":"bounded","scope":["src"],"assumptions":[],"design":"same","open_choices":[],"verification":["check"]})).unwrap()).unwrap();
    success(case.fixture.run(&[
        "review",
        "init",
        "--subject",
        "excluded",
        "--contract",
        contract.to_str().unwrap(),
        "--repository",
        case.fixture.root.to_str().unwrap(),
        "--scope",
        "src",
        "--exclude",
        "src/b.rs",
        "--json",
    ]));
    case.fixture.approve("excluded", "pre-edit", false);
    let inspection = case.fixture.inspect("excluded", "pre-edit");
    failure(
        case.fixture.run(&[
            "review",
            "bind-worktree",
            "--subject",
            "excluded",
            "--binding",
            "worker",
            "--expected-version",
            inspection["version"].as_str().unwrap(),
            "--worktree",
            case.worker.to_str().unwrap(),
            "--scope",
            "src",
            "--json",
        ]),
        4,
        "review_invalid",
    );
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(
            case.fixture.root.parent().unwrap(),
            case.worker.join("src/escape"),
        )
        .unwrap();
        failure(
            case.fixture.run(&[
                "review",
                "bind-worktree",
                "--subject",
                "excluded",
                "--binding",
                "escape",
                "--expected-version",
                inspection["version"].as_str().unwrap(),
                "--worktree",
                case.worker.to_str().unwrap(),
                "--scope",
                "src/escape/new.rs",
                "--json",
            ]),
            4,
            "review_invalid",
        );
    }
}

#[test]
fn disjoint_worktrees_have_separate_evidence_and_archive_changes_stale_final_review() {
    let case = WorktreeFixture::new("binding-separate");
    case.bind("src/a.rs");
    let second = case.fixture.root.with_extension("second-worker");
    assert!(
        Command::new("git")
            .args(["worktree", "add", "-qb", "second"])
            .arg(&second)
            .current_dir(&case.fixture.root)
            .output()
            .unwrap()
            .status
            .success()
    );
    let parent = case.fixture.inspect(&case.subject, "pre-edit");
    let bound = success(case.fixture.run(&[
        "review",
        "bind-worktree",
        "--subject",
        &case.subject,
        "--binding",
        "second",
        "--expected-version",
        parent["version"].as_str().unwrap(),
        "--worktree",
        second.to_str().unwrap(),
        "--scope",
        "src/b.rs",
        "--json",
    ]));
    assert_ne!(bound["baseline_id"], case.inspect()["baseline_id"]);
    fs::write(case.worker.join("src/a.rs"), "first worker\n").unwrap();
    success(case.check("resume"));
    let second_evidence = success(case.fixture.run(&[
        "review",
        "inspect-worktree",
        "--subject",
        &case.subject,
        "--binding",
        "second",
        "--json",
    ]));
    assert!(
        second_evidence["manifest"]["entries"]
            .as_array()
            .unwrap()
            .iter()
            .all(|entry| entry["change"] == "unchanged")
    );
    case.git_worker(&["add", "src/a.rs"]);
    case.git_worker(&["commit", "-qm", "first worker"]);
    let first_commit = case.git_worker(&["rev-parse", "HEAD"]);
    assert!(
        Command::new("git")
            .args(["merge", "--ff-only", "worker"])
            .current_dir(&case.fixture.root)
            .output()
            .unwrap()
            .status
            .success()
    );
    let first = case.inspect();
    success(case.release(first["version"].as_str().unwrap(), &first_commit));
    let second_evidence = success(case.fixture.run(&[
        "review",
        "inspect-worktree",
        "--subject",
        &case.subject,
        "--binding",
        "second",
        "--json",
    ]));
    let second_commit = String::from_utf8(
        Command::new("git")
            .args(["rev-parse", "HEAD"])
            .current_dir(&second)
            .output()
            .unwrap()
            .stdout,
    )
    .unwrap();
    success(case.fixture.run(&[
        "review",
        "release-worktree",
        "--subject",
        &case.subject,
        "--binding",
        "second",
        "--expected-version",
        second_evidence["version"].as_str().unwrap(),
        "--commit",
        second_commit.trim(),
        "--json",
    ]));
    assert!(
        Command::new("git")
            .args(["worktree", "remove"])
            .arg(&second)
            .current_dir(&case.fixture.root)
            .output()
            .unwrap()
            .status
            .success()
    );
    case.fixture.approve(&case.subject, "implementation", true);
    success(case.fixture.run(&[
        "review",
        "check",
        "--subject",
        &case.subject,
        "--checkpoint",
        "complete",
        "--json",
    ]));
    let record = case
        .fixture
        .root
        .join("memory-bank/working/review-gates")
        .join(&case.subject)
        .join("worktrees/worker/binding.json");
    let mut binding: Value = serde_json::from_slice(&fs::read(&record).unwrap()).unwrap();
    binding["archive"]["note"] = json!("changed archive");
    fs::write(&record, serde_json::to_vec_pretty(&binding).unwrap()).unwrap();
    failure(
        case.fixture.run(&[
            "review",
            "check",
            "--subject",
            &case.subject,
            "--checkpoint",
            "complete",
            "--json",
        ]),
        4,
        "review_stale_changes",
    );
}

#[test]
fn stale_execution_can_archive_integrated_source_only_under_current_parent_approval() {
    let case = WorktreeFixture::new("binding-refresh");
    case.bind("src/a.rs");
    fs::write(case.worker.join("src/a.rs"), "worker result\n").unwrap();
    case.git_worker(&["add", "src/a.rs"]);
    case.git_worker(&["commit", "-qm", "worker result"]);
    let commit = case.git_worker(&["rev-parse", "HEAD"]);
    let plan = case
        .fixture
        .root
        .join("memory-bank/working/plans/example/plan.md");
    fs::write(
        &plan,
        fs::read_to_string(&plan).unwrap().replace(
            "Implement the solution.",
            "The reviewed solution has changed.",
        ),
    )
    .unwrap();
    case.fixture.approve(&case.subject, "pre-edit", false);
    failure(case.check("resume"), 4, "review_invalid");
    let stale = case.inspect();
    assert_eq!(stale["execution_ready"], false);
    assert!(stale["version"].is_string());
    assert!(
        Command::new("git")
            .args(["merge", "--ff-only", "worker"])
            .current_dir(&case.fixture.root)
            .output()
            .unwrap()
            .status
            .success()
    );
    let current = case.inspect();
    success(case.release(current["version"].as_str().unwrap(), &commit));
    assert_eq!(case.inspect()["archive"]["approval_changed"], true);
    failure(
        case.fixture.run(&[
            "review",
            "check",
            "--subject",
            &case.subject,
            "--checkpoint",
            "complete",
            "--json",
        ]),
        4,
        "review_missing",
    );
    case.fixture.approve(&case.subject, "implementation", false);
    success(case.fixture.run(&[
        "review",
        "check",
        "--subject",
        &case.subject,
        "--checkpoint",
        "complete",
        "--json",
    ]));
}

#[test]
fn missing_worktree_can_be_abandoned_without_recreation_or_deleting_recovery_refs() {
    let case = WorktreeFixture::new("binding-abandon");
    case.fixture.approve(&case.subject, "pre-edit", false);
    case.bind("src/a.rs");
    fs::write(case.worker.join("src/a.rs"), "retained branch result\n").unwrap();
    case.git_worker(&["add", "src/a.rs"]);
    case.git_worker(&["commit", "-qm", "retained result"]);
    assert!(
        Command::new("git")
            .args(["worktree", "remove", "--force"])
            .arg(&case.worker)
            .current_dir(&case.fixture.root)
            .output()
            .unwrap()
            .status
            .success()
    );
    assert!(!case.worker.exists());
    let unavailable = case.inspect();
    assert!(
        !case.worker.exists(),
        "read-only inspection recreated the missing worktree"
    );
    assert!(unavailable["unavailable"].is_string());
    let plan = case
        .fixture
        .root
        .join("memory-bank/working/plans/example/plan.md");
    success(case.fixture.transition(&plan, "blocked"));
    let blocked_inspection = case.inspect();
    failure(
        case.fixture.run(&[
            "review",
            "abandon-worktree",
            "--subject",
            &case.subject,
            "--binding",
            "worker",
            "--expected-version",
            blocked_inspection["version"].as_str().unwrap(),
            "--reason",
            "Missing worker; retain branch for diagnosis",
            "--json",
        ]),
        4,
        "review_invalid",
    );
    success(case.fixture.transition(&plan, "active"));
    let current = case.inspect();
    success(case.fixture.run(&[
        "review",
        "abandon-worktree",
        "--subject",
        &case.subject,
        "--binding",
        "worker",
        "--expected-version",
        current["version"].as_str().unwrap(),
        "--reason",
        "Missing worker; retain branch for diagnosis",
        "--json",
    ]));
    assert!(!case.worker.exists());
    assert!(
        Command::new("git")
            .args(["show-ref", "--verify", "refs/heads/worker"])
            .current_dir(&case.fixture.root)
            .output()
            .unwrap()
            .status
            .success()
    );
    assert_eq!(
        fs::read_to_string(case.fixture.root.join("src/a.rs")).unwrap(),
        "baseline\n"
    );
    assert_eq!(case.inspect()["state"], "abandoned");
    failure(
        case.fixture.run(&[
            "review",
            "check",
            "--subject",
            &case.subject,
            "--checkpoint",
            "complete",
            "--json",
        ]),
        4,
        "review_missing",
    );
    case.fixture.approve(&case.subject, "implementation", false);
    success(case.fixture.run(&[
        "review",
        "check",
        "--subject",
        &case.subject,
        "--checkpoint",
        "complete",
        "--json",
    ]));
}
