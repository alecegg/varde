//! Run declared skill mutations through the ordinary eval runner.

use std::fs;
use std::path::{Component, Path};

use serde::Deserialize;
use serde_json::{Value, json};

use crate::error::LearnError;

use super::{OutputHarness, OutputRequest, run_output};

#[derive(Debug, Deserialize)]
struct MutationFile {
    mutations: Vec<Mutation>,
}

#[derive(Debug, Deserialize)]
struct Mutation {
    id: String,
    file: String,
    remove: String,
    #[serde(default)]
    replace_with: Option<String>,
    #[serde(default)]
    negative: bool,
    evals: Vec<String>,
}

/// Apply each listed mutation to an isolated skill copy; positive mutations
/// must fail their selected evals and negative controls must pass.
pub fn calibrate(skill_dir: &Path, harness: OutputHarness) -> Result<Value, LearnError> {
    let source = fs::canonicalize(skill_dir).map_err(|error| {
        LearnError::Usage(format!(
            "skill dir not found: {}: {error}",
            skill_dir.display()
        ))
    })?;
    if !source.join("SKILL.md").is_file() {
        return Err(LearnError::Usage(format!(
            "no SKILL.md in {}",
            source.display()
        )));
    }
    let mutation_path = source.join("evals/mutations.json");
    let text = fs::read_to_string(&mutation_path).map_err(|error| {
        LearnError::Usage(format!("cannot read {}: {error}", mutation_path.display()))
    })?;
    let mutations: MutationFile = serde_json::from_str(&text).map_err(|error| {
        LearnError::Usage(format!("invalid {}: {error}", mutation_path.display()))
    })?;
    if mutations.mutations.is_empty() {
        return Err(LearnError::Usage("mutation list must not be empty".into()));
    }
    if !mutations.mutations.iter().any(|mutation| mutation.negative) {
        return Err(LearnError::Usage(
            "mutation list must include at least one negative mutation".into(),
        ));
    }

    let workspace = tempfile::tempdir().map_err(|error| {
        LearnError::Usage(format!("cannot create calibration workspace: {error}"))
    })?;
    let mut results = Vec::new();
    for mutation in &mutations.mutations {
        if mutation.id.trim().is_empty() || mutation.evals.is_empty() {
            return Err(LearnError::Usage(format!(
                "mutation must have an id and evals: {}",
                mutation.id
            )));
        }
        let relative = Path::new(&mutation.file);
        if relative.as_os_str().is_empty()
            || relative.is_absolute()
            || relative
                .components()
                .any(|part| !matches!(part, Component::Normal(_)))
        {
            return Err(LearnError::Usage(format!(
                "invalid mutation file path: {}",
                mutation.file
            )));
        }
        let copy = workspace.path().join(format!("mutation-{}", results.len()));
        copy_skill(&source, &copy)?;
        let target = copy.join(relative);
        let original = fs::read_to_string(&target).map_err(|error| {
            LearnError::Usage(format!(
                "cannot read mutation target {}: {error}",
                target.display()
            ))
        })?;
        if mutation.remove.is_empty() || original.matches(&mutation.remove).count() != 1 {
            return Err(LearnError::Usage(format!(
                "mutation {} must match exactly one non-empty text span in {}",
                mutation.id, mutation.file
            )));
        }
        fs::write(
            &target,
            original.replacen(
                &mutation.remove,
                mutation.replace_with.as_deref().unwrap_or(""),
                1,
            ),
        )
        .map_err(|error| {
            LearnError::Usage(format!("cannot apply mutation {}: {error}", mutation.id))
        })?;
        let report = run_selected(&copy, harness, mutation.evals.clone(), workspace.path())?;
        let evals_match = mutation.evals.iter().all(|id| {
            report.records.iter().any(|record| {
                record.eval_id == *id
                    && record.outcome.as_str() == "completed"
                    && record.total_assertions > 0
                    && if mutation.negative {
                        record.passed_assertions == record.total_assertions
                    } else {
                        record.passed_assertions < record.total_assertions
                    }
            })
        });
        results.push(
            json!({"mutation": mutation.id, "negative": mutation.negative, "evals": mutation.evals, "passed": evals_match}),
        );
    }

    let restored = workspace.path().join("restored");
    copy_skill(&source, &restored)?;
    let restored_ids = mutations
        .mutations
        .iter()
        .flat_map(|mutation| mutation.evals.iter().cloned())
        .collect::<std::collections::BTreeSet<_>>()
        .into_iter()
        .collect();
    let restored_report = run_selected(&restored, harness, restored_ids, workspace.path())?;
    let restored_passed = !restored_report.records.is_empty()
        && restored_report.records.iter().all(|record| {
            record.outcome.as_str() == "completed"
                && record.total_assertions > 0
                && record.passed_assertions == record.total_assertions
        });
    let passed = results.iter().all(|result| result["passed"] == true) && restored_passed;
    Ok(json!({"passed": passed, "mutations": results, "restored_passed": restored_passed}))
}

fn run_selected(
    skill_dir: &Path,
    harness: OutputHarness,
    eval_ids: Vec<String>,
    workspace: &Path,
) -> Result<super::OutputReport, LearnError> {
    run_output(&OutputRequest {
        harness,
        model: None,
        judge_model: None,
        skill_dir: skill_dir.to_path_buf(),
        runs: 1,
        iteration: 1,
        workspace: Some(workspace.join(format!(
            "run-{}",
            skill_dir.file_name().unwrap_or_default().to_string_lossy()
        ))),
        eval_ids,
        timeout_seconds: 300,
        sandbox_dir: None,
        no_baseline: true,
    })
}

fn copy_skill(source: &Path, destination: &Path) -> Result<(), LearnError> {
    fn copy_dir(source: &Path, destination: &Path) -> std::io::Result<()> {
        fs::create_dir_all(destination)?;
        for entry in fs::read_dir(source)? {
            let entry = entry?;
            let from = entry.path();
            let to = destination.join(entry.file_name());
            if from.is_dir() {
                copy_dir(&from, &to)?;
            } else {
                fs::copy(from, to)?;
            }
        }
        Ok(())
    }
    let _ = fs::remove_dir_all(destination);
    copy_dir(source, destination).map_err(|error| {
        LearnError::Usage(format!(
            "cannot copy skill to {}: {error}",
            destination.display()
        ))
    })
}
