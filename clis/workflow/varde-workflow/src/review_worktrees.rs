//! Explicit scoped worktree authorization without changing parent repository identity.
use crate::{cli, review_contract, review_coverage, review_gates};
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
    process::Command,
};

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Binding {
    schema_version: u32,
    subject_id: String,
    binding_id: String,
    parent_repository: PathBuf,
    worktree_repository: PathBuf,
    git_common_directory: PathBuf,
    branch: String,
    base_commit: String,
    scope: Vec<String>,
    task_path: Option<PathBuf>,
    task_fingerprint: Option<String>,
    parent_contract_fingerprint: String,
    parent_baseline_id: String,
    parent_pre_edit_revision: String,
    baseline_id: String,
    snapshots: BTreeMap<String, review_coverage::SnapshotEntry>,
    state: String,
    archive: Option<Value>,
}
fn git(repo: &Path, args: &[&str]) -> Result<String> {
    let output = Command::new("git").args(args).current_dir(repo).output()?;
    if !output.status.success() {
        return Err(review_gates::invalid(format!(
            "Git identity check failed: {}",
            String::from_utf8_lossy(&output.stderr)
        )));
    }
    Ok(String::from_utf8(output.stdout)?.trim().to_owned())
}
fn directory(repo: &Path, subject: &str, id: &str) -> Result<PathBuf> {
    review_gates::validate_subject_id(id)?;
    Ok(review_gates::subject_directory(repo, subject)?
        .join("worktrees")
        .join(id))
}
fn read(repo: &Path, subject: &str, id: &str) -> Result<Binding> {
    let dir = directory(repo, subject, id)?;
    let path = dir.join("binding.json");
    if fs::symlink_metadata(dir.parent().unwrap())?
        .file_type()
        .is_symlink()
        || fs::symlink_metadata(&dir)?.file_type().is_symlink()
        || fs::symlink_metadata(&path)?.file_type().is_symlink()
    {
        return Err(review_gates::invalid(
            "binding storage must not be a symlink",
        ));
    }
    let binding: Binding = serde_json::from_slice(&fs::read(&path)?)?;
    if binding.schema_version != 1
        || binding.subject_id != subject
        || binding.binding_id != id
        || binding.parent_repository != repo
        || !["active", "released", "abandoned"].contains(&binding.state.as_str())
    {
        return Err(review_gates::invalid(
            "worktree binding identity or state is invalid",
        ));
    }
    let fingerprint = review_coverage::baseline_fingerprint(
        &binding.binding_id,
        &binding.scope,
        &[],
        &binding.snapshots,
        &Default::default(),
    )?;
    if fingerprint != binding.baseline_id {
        return Err(review_gates::invalid("worktree baseline metadata changed"));
    }
    review_coverage::verify_baseline_blobs(&dir, &binding.snapshots)?;
    Ok(binding)
}
fn all(repo: &Path, subject: &str) -> Result<Vec<Binding>> {
    let root = review_gates::subject_directory(repo, subject)?.join("worktrees");
    if !root.exists() {
        return Ok(vec![]);
    }
    if fs::symlink_metadata(&root)?.file_type().is_symlink() {
        return Err(review_gates::invalid("binding root must not be a symlink"));
    }
    let mut bindings = vec![];
    for entry in fs::read_dir(root)? {
        let entry = entry?;
        let id = entry.file_name().to_string_lossy().into_owned();
        if !id.starts_with('.') {
            bindings.push(read(repo, subject, &id)?);
        }
    }
    bindings.sort_by(|a, b| a.binding_id.cmp(&b.binding_id));
    Ok(bindings)
}
pub fn fingerprint_evidence(repo: &Path, subject: &str) -> Result<Value> {
    Ok(serde_json::to_value(all(repo, subject)?)?)
}
pub fn has_active(repo: &Path, subject: &str) -> Result<bool> {
    Ok(all(repo, subject)?.iter().any(|b| b.state == "active"))
}
fn within(path: &str, roots: &[String]) -> bool {
    roots
        .iter()
        .any(|root| root == "." || path == root || path.starts_with(&format!("{root}/")))
}
fn task_contract(path: &Path) -> Result<(String, Vec<String>)> {
    let bytes = fs::read(path)?;
    let (fm, _) = varde_workflow_core::frontmatter::parse(&bytes)?;
    let mapping = fm
        .as_mapping()
        .context("task frontmatter must be a mapping")?;
    if mapping
        .get(serde_yaml::Value::String("type".into()))
        .and_then(serde_yaml::Value::as_str)
        != Some("task")
        || mapping
            .get(serde_yaml::Value::String("status".into()))
            .and_then(serde_yaml::Value::as_str)
            != Some("in_progress")
    {
        return Err(review_gates::invalid(
            "bound task must be an in_progress task",
        ));
    }
    let mut paths = vec![];
    for key in ["modifies", "creates", "renames", "verification_resources"] {
        let value = mapping
            .get(serde_yaml::Value::String(key.to_owned()))
            .context("complete task ownership is required for binding")?;
        for entry in value
            .as_sequence()
            .context("task ownership must be a list")?
        {
            let entry = entry
                .as_str()
                .context("task ownership must contain strings")?;
            if key == "renames" {
                let (old, new) = entry
                    .split_once("->")
                    .context("rename must be old/path -> new/path")?;
                paths.extend([old.trim().to_owned(), new.trim().to_owned()]);
            } else if key != "verification_resources" {
                paths.push(entry.to_owned());
            }
        }
    }
    Ok((review_contract::contract_fingerprint(&bytes)?, paths))
}

fn common(repo: &Path) -> Result<PathBuf> {
    Ok(PathBuf::from(git(
        repo,
        &["rev-parse", "--path-format=absolute", "--git-common-dir"],
    )?)
    .canonicalize()?)
}
fn identity(binding: &Binding) -> Result<()> {
    let worker = binding.worktree_repository.canonicalize()?;
    if worker != binding.worktree_repository
        || PathBuf::from(git(&worker, &["rev-parse", "--show-toplevel"])?).canonicalize()? != worker
        || common(&worker)? != binding.git_common_directory
        || common(&binding.parent_repository)? != binding.git_common_directory
    {
        return Err(review_gates::invalid(
            "registered worktree repository identity changed",
        ));
    }
    if git(&worker, &["symbolic-ref", "--quiet", "HEAD"])? != binding.branch {
        return Err(review_gates::invalid("worktree branch identity changed"));
    }
    let registry = git(
        &binding.parent_repository,
        &["worktree", "list", "--porcelain"],
    )?;
    if !registry.split("\n\n").any(|record| {
        record
            .lines()
            .any(|line| line == format!("worktree {}", worker.display()))
            && record
                .lines()
                .any(|line| line == format!("branch {}", binding.branch))
    }) {
        return Err(review_gates::invalid(
            "worktree branch/path is not registered",
        ));
    }
    git(
        &worker,
        &["merge-base", "--is-ancestor", &binding.base_commit, "HEAD"],
    )?;
    Ok(())
}
fn git_paths(repo: &Path, args: &[&str]) -> Result<Vec<String>> {
    let output = Command::new("git").args(args).current_dir(repo).output()?;
    if !output.status.success() {
        return Err(review_gates::invalid("Git path inventory failed"));
    }
    String::from_utf8(output.stdout)?
        .split('\0')
        .filter(|path| !path.is_empty())
        .map(|path| Ok(path.to_owned()))
        .collect()
}
fn untracked(repo: &Path) -> Result<Vec<String>> {
    git_paths(repo, &["ls-files", "--others", "--exclude-standard", "-z"])
}
fn changed_paths(binding: &Binding) -> Result<Vec<String>> {
    let repo = &binding.worktree_repository;
    let mut paths = git_paths(
        repo,
        &[
            "diff",
            "--name-only",
            "--no-renames",
            "-z",
            &binding.base_commit,
            "--",
        ],
    )?;
    paths.extend(untracked(repo)?);
    paths.sort();
    paths.dedup();
    paths.retain(|path| {
        !matches!(
            path.as_str(),
            ".varde-workflow.lock" | ".varde-workflow-journal.json"
        ) || git(repo, &["ls-files", "--error-unmatch", "--", path]).is_ok()
    });
    Ok(paths)
}

fn active_parent(parent: &Path, subject: &str) -> Result<()> {
    if let Some(plan) = review_gates::load_subject(parent, subject)?.plan_path {
        let (frontmatter, _) = varde_workflow_core::frontmatter::parse(&fs::read(plan)?)?;
        if frontmatter
            .get("status")
            .and_then(serde_yaml::Value::as_str)
            != Some("active")
        {
            return Err(review_gates::invalid(
                "persisted parent plan must be active for worktree execution",
            ));
        }
    }
    Ok(())
}
fn validate(parent: &Path, binding: &Binding) -> Result<review_gates::CheckReport> {
    if binding.state != "active" {
        return Err(review_gates::invalid("worktree binding has been released"));
    }
    identity(binding)?;
    active_parent(parent, &binding.subject_id)?;
    let approval = review_gates::check(parent, &binding.subject_id, "start")?;
    if !approval.ready {
        return Ok(approval);
    }
    let consumed = &approval.consumed;
    if consumed.contract_fingerprint != binding.parent_contract_fingerprint
        || consumed.baseline_id != binding.parent_baseline_id
        || consumed.pre_edit_revision.as_deref() != Some(&binding.parent_pre_edit_revision)
    {
        return Err(review_gates::invalid(
            "parent approval changed after authorization",
        ));
    }
    if let Some(task) = &binding.task_path
        && Some(task_contract(task)?.0) != binding.task_fingerprint
    {
        return Err(review_gates::invalid(
            "task ownership or verification changed after authorization",
        ));
    }
    for path in changed_paths(binding)? {
        review_gates::normalize_relative_path(&binding.worktree_repository, &path)?;
        if !within(&path, &binding.scope) {
            return Err(review_gates::invalid(format!(
                "worktree changed path outside its authorized scope: {path}"
            )));
        }
    }
    Ok(approval)
}
fn files(repo: &Path, scope: &[String]) -> Result<BTreeMap<String, review_coverage::CurrentEntry>> {
    review_coverage::inventory(repo, &review_gates::working_root(repo)?, scope, &[])
}
fn same_files(
    a: &BTreeMap<String, review_coverage::CurrentEntry>,
    b: &BTreeMap<String, review_coverage::CurrentEntry>,
) -> bool {
    fn comparable(
        entries: &BTreeMap<String, review_coverage::CurrentEntry>,
    ) -> BTreeMap<String, review_coverage::SnapshotEntry> {
        entries
            .iter()
            .map(|(path, entry)| {
                let mut snapshot = entry.snapshot.clone();
                snapshot.content_path = None;
                (path.clone(), snapshot)
            })
            .collect()
    }
    comparable(a) == comparable(b)
}

pub fn bind(parent: &Path, args: &cli::ReviewBindWorktreeArgs) -> Result<Value> {
    active_parent(parent, &args.subject)?;
    let subject = review_gates::load_subject(parent, &args.subject)?;
    review_gates::ensure_expected_version(parent, &subject, "pre-edit", &args.expected_version)?;
    let approval = review_gates::check(parent, &args.subject, "start")?;
    if !approval.ready {
        return Err(review_gates::invalid(
            "parent review is not ready for authorization",
        ));
    }
    let worker = args.worktree.canonicalize()?;
    if worker == parent {
        return Err(review_gates::invalid(
            "binding requires a distinct linked worktree",
        ));
    }
    let dir = directory(parent, &args.subject, &args.binding)?;
    if dir.exists() {
        return Err(review_gates::conflict("worktree binding already exists"));
    }
    let mut scope = vec![];
    for raw in &args.scope {
        let path = review_gates::normalize_relative_path(parent, raw)?;
        review_gates::normalize_relative_path(&worker, raw)?;
        if !within(&path, &subject.scope)
            || subject.excludes.iter().any(|excluded| {
                within(&path, std::slice::from_ref(excluded))
                    || within(excluded, std::slice::from_ref(&path))
            })
        {
            return Err(review_gates::invalid(
                "worktree scope exceeds approval or includes excluded paths",
            ));
        }
        scope.push(path);
    }
    scope.sort();
    scope.dedup();
    let (task_path, task_fingerprint) = if let Some(task) = &args.task {
        let task = task.canonicalize()?;
        let plan = subject
            .plan_path
            .as_ref()
            .context("task binding requires a persisted parent plan")?;
        if task.parent() != Some(plan.parent().unwrap().join("tasks").as_path()) {
            return Err(review_gates::invalid(
                "task does not belong to subject plan",
            ));
        }
        let (fingerprint, paths) = task_contract(&task)?;
        let mut owned = paths
            .iter()
            .map(|raw| review_gates::normalize_relative_path(parent, raw))
            .collect::<Result<Vec<_>>>()?;
        owned.sort();
        owned.dedup();
        if owned != scope {
            return Err(review_gates::invalid(
                "binding scope must equal declared task ownership",
            ));
        }
        (Some(task), Some(fingerprint))
    } else {
        (None, None)
    };
    let mut binding = Binding {
        schema_version: 1,
        subject_id: args.subject.clone(),
        binding_id: args.binding.clone(),
        parent_repository: parent.to_path_buf(),
        worktree_repository: worker.clone(),
        git_common_directory: common(parent)?,
        branch: git(&worker, &["symbolic-ref", "--quiet", "HEAD"])?,
        base_commit: git(parent, &["rev-parse", "HEAD"])?,
        scope,
        task_path,
        task_fingerprint,
        parent_contract_fingerprint: approval.consumed.contract_fingerprint,
        parent_baseline_id: approval.consumed.baseline_id,
        parent_pre_edit_revision: approval
            .consumed
            .pre_edit_revision
            .context("approval record missing")?,
        baseline_id: String::new(),
        snapshots: BTreeMap::new(),
        state: "active".into(),
        archive: None,
    };
    identity(&binding)?;
    if git(&worker, &["rev-parse", "HEAD"])? != binding.base_commit
        || !changed_paths(&binding)?.is_empty()
    {
        return Err(review_gates::invalid(
            "worktree must start clean at parent HEAD",
        ));
    }
    let current = files(&worker, &binding.scope)?;
    if !same_files(&current, &files(parent, &binding.scope)?) {
        return Err(review_gates::invalid(
            "worker baseline differs from parent source",
        ));
    }
    let root = dir.parent().unwrap();
    fs::create_dir_all(root)?;
    if fs::symlink_metadata(root)?.file_type().is_symlink() {
        return Err(review_gates::invalid("binding root must not be a symlink"));
    }
    let staging = root.join(format!(".{}-{}", args.binding, std::process::id()));
    fs::create_dir(&staging)?;
    fs::create_dir_all(staging.join("baseline/blobs"))?;
    let result: Result<()> = (|| {
        review_coverage::capture_baseline(&staging, &current, &mut binding.snapshots)?;
        review_coverage::relocate_content_paths(&mut binding.snapshots, &staging, &dir);
        binding.baseline_id = review_coverage::baseline_fingerprint(
            &binding.binding_id,
            &binding.scope,
            &[],
            &binding.snapshots,
            &Default::default(),
        )?;
        fs::write(
            staging.join("binding.json"),
            serde_json::to_vec_pretty(&binding)?,
        )?;
        review_gates::ensure_expected_version(
            parent,
            &subject,
            "pre-edit",
            &args.expected_version,
        )?;
        identity(&binding)?;
        fs::rename(&staging, &dir)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_dir_all(&staging);
    }
    result?;
    inspect(parent, &args.subject, &args.binding)
}
fn evidence(parent: &Path, binding: &Binding) -> Result<Value> {
    let current = if binding.worktree_repository.is_dir() {
        files(&binding.worktree_repository, &binding.scope)
    } else {
        Err(review_gates::invalid(
            "registered worktree is unavailable; source evidence cannot be gathered",
        ))
    };
    let (manifest, unavailable) = match current {
        Ok(current) => (
            review_coverage::manifest(&binding.snapshots, &Default::default(), &current),
            None,
        ),
        Err(error) => (vec![], Some(error.to_string())),
    };
    let fingerprint = review_contract::fingerprint_json(
        "varde-worktree-change-v1",
        &json!({"baseline_id":binding.baseline_id,"entries":manifest,"unavailable":unavailable}),
    )?;
    let parent_approval = review_gates::check(parent, &binding.subject_id, "start")?;
    let version = review_contract::fingerprint_json(
        "varde-worktree-inspection-v1",
        &json!({"binding":binding,"fingerprint":fingerprint,"parent":parent_approval.consumed}),
    )?;
    Ok(
        json!({"binding_id":binding.binding_id,"version":version,"baseline_id":binding.baseline_id,"change_fingerprint":fingerprint,"manifest":{"entries":manifest},"unavailable":unavailable,"binding":binding,"current_parent":parent_approval.consumed}),
    )
}
pub fn inspect(parent: &Path, subject: &str, id: &str) -> Result<Value> {
    let binding = read(parent, subject, id)?;
    if binding.state != "active" {
        return Ok(json!({"binding_id":id,"state":binding.state,"archive":binding.archive}));
    }
    let mut result = evidence(parent, &binding)?;
    match validate(parent, &binding) {
        Ok(check) => {
            result["execution_ready"] = json!(check.ready);
            result["blockers"] = json!(check.blockers);
        }
        Err(error) => {
            result["execution_ready"] = json!(false);
            result["blockers"] = json!([{"code":"review_invalid","message":error.to_string()}]);
        }
    }
    Ok(result)
}
fn validate_archive(parent: &Path, binding: &Binding) -> Result<review_gates::CheckReport> {
    if binding.state != "active" {
        return Err(review_gates::invalid("binding has already been archived"));
    }
    identity(binding)?;
    active_parent(parent, &binding.subject_id)?;
    let approval = review_gates::check(parent, &binding.subject_id, "start")?;
    if !approval.ready {
        return Err(review_gates::invalid(
            "current parent approval blocks archival",
        ));
    }
    let subject = review_gates::load_subject(parent, &binding.subject_id)?;
    for path in &binding.scope {
        review_gates::normalize_relative_path(parent, path)?;
        if !within(path, &subject.scope)
            || subject.excludes.iter().any(|excluded| {
                within(path, std::slice::from_ref(excluded))
                    || within(excluded, std::slice::from_ref(path))
            })
        {
            return Err(review_gates::invalid(
                "original binding scope is outside current parent approval",
            ));
        }
    }
    for path in changed_paths(binding)? {
        review_gates::normalize_relative_path(&binding.worktree_repository, &path)?;
        if !within(&path, &binding.scope) {
            return Err(review_gates::invalid(
                "worker has changes outside its original authorization",
            ));
        }
    }
    Ok(approval)
}

pub fn check(
    parent: &Path,
    subject: &str,
    id: &str,
    worker: &Path,
    checkpoint: &str,
) -> Result<review_gates::CheckReport> {
    if !["start", "resume"].contains(&checkpoint) {
        return Err(review_gates::invalid(
            "binding authorizes start/resume only; completion belongs to parent",
        ));
    }
    let binding = read(parent, subject, id)?;
    if worker.canonicalize()? != binding.worktree_repository {
        return Err(review_gates::invalid(
            "check worktree does not match binding",
        ));
    }
    let mut report = validate(parent, &binding)?;
    report.checkpoint = checkpoint.to_owned();
    Ok(report)
}
pub fn release(parent: &Path, args: &cli::ReviewReleaseWorktreeArgs) -> Result<Value> {
    let mut binding = read(parent, &args.subject, &args.binding)?;
    let approved = validate_archive(parent, &binding)?;
    let current = evidence(parent, &binding)?;
    if current["version"].as_str() != Some(&args.expected_version) {
        return Err(review_gates::conflict(
            "worktree evidence changed after inspection",
        ));
    }
    let commit = git(
        &binding.worktree_repository,
        &[
            "rev-parse",
            "--verify",
            &format!("{}^{{commit}}", args.commit),
        ],
    )?;
    if git(&binding.worktree_repository, &["rev-parse", "HEAD"])? != commit {
        return Err(review_gates::invalid(
            "release commit must match worker HEAD",
        ));
    }
    git(parent, &["merge-base", "--is-ancestor", &commit, "HEAD"])?;
    if !same_files(
        &files(&binding.worktree_repository, &binding.scope)?,
        &files(parent, &binding.scope)?,
    ) {
        return Err(review_gates::invalid(
            "integrated source does not match worker evidence",
        ));
    }
    if !git_paths(
        &binding.worktree_repository,
        &["diff", "--name-only", "-z", "HEAD", "--"],
    )?
    .is_empty()
        || untracked(&binding.worktree_repository)?
            .iter()
            .any(|path| within(path, &binding.scope))
    {
        return Err(review_gates::invalid(
            "worker source must be committed before release",
        ));
    }
    if evidence(parent, &binding)?["version"] != current["version"] {
        return Err(review_gates::conflict("worktree changed before archive"));
    }
    binding.state = "released".into();
    let approval_changed = approved.consumed.contract_fingerprint
        != binding.parent_contract_fingerprint
        || approved.consumed.baseline_id != binding.parent_baseline_id
        || approved.consumed.pre_edit_revision.as_deref()
            != Some(&binding.parent_pre_edit_revision);
    binding.archive = Some(
        json!({"commit":commit,"evidence":current,"approval_changed":approval_changed,"current_parent":approved.consumed}),
    );
    review_gates::write_atomic(
        &directory(parent, &args.subject, &args.binding)?.join("binding.json"),
        &serde_json::to_vec_pretty(&binding)?,
    )?;
    Ok(json!({"binding_id":args.binding,"state":"released","commit":commit}))
}

pub fn worktree_for(parent: &Path, subject: &str, binding: &str) -> Result<Option<PathBuf>> {
    let binding = read(parent, subject, binding)?;
    Ok(
        (binding.state == "active" && binding.worktree_repository.exists())
            .then_some(binding.worktree_repository),
    )
}

pub fn requires_final_review(parent: &Path, subject: &str) -> Result<bool> {
    Ok(all(parent, subject)?
        .iter()
        .any(|binding| binding.state != "active"))
}

pub fn abandon(parent: &Path, args: &cli::ReviewAbandonWorktreeArgs) -> Result<Value> {
    if args.reason.trim().is_empty() {
        return Err(review_gates::invalid(
            "abandonment requires a concrete reason",
        ));
    }
    active_parent(parent, &args.subject)?;
    let mut binding = read(parent, &args.subject, &args.binding)?;
    if binding.state != "active" {
        return Err(review_gates::invalid("binding has already been archived"));
    }
    let approval = review_gates::check(parent, &args.subject, "start")?;
    if !approval.ready {
        return Err(review_gates::invalid(
            "current independent parent approval is required to abandon authorization",
        ));
    }
    let current = inspect(parent, &args.subject, &args.binding)?;
    if current["version"].as_str() != Some(&args.expected_version) {
        return Err(review_gates::conflict(
            "worktree evidence changed after inspection",
        ));
    }
    if inspect(parent, &args.subject, &args.binding)?["version"] != current["version"] {
        return Err(review_gates::conflict(
            "worktree evidence changed before abandonment",
        ));
    }
    binding.state = "abandoned".into();
    binding.archive = Some(
        json!({"reason":args.reason,"evidence":current,"current_parent":approval.consumed,"recovery_refs_retained":true}),
    );
    review_gates::write_atomic(
        &directory(parent, &args.subject, &args.binding)?.join("binding.json"),
        &serde_json::to_vec_pretty(&binding)?,
    )?;
    Ok(
        json!({"binding_id":args.binding,"state":"abandoned","worktree":binding.worktree_repository,"branch":binding.branch,"recovery_refs_retained":true}),
    )
}
