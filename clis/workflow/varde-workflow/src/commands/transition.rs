use crate::cli::TransitionArgs;
use crate::commands::error::{InternalError, report_error};
use crate::output::{print_failure, print_success};
use crate::review_checkpoints;
use crate::review_gates;
use crate::workflow_graph::{ArtifactGraph, Blocker, WorkflowArtifact, content_with_status};
use crate::workflow_schema::WorkflowSchema;
use anyhow::Result;
use serde_json::json;

pub fn run(args: TransitionArgs) -> Result<()> {
    let repository = match review_checkpoints::repository_for(&args.artifact) {
        Ok(repository) => repository,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    let lock = match crate::review_lock::ProjectLock::acquire(&repository) {
        Ok(lock) => lock,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    let schema = match WorkflowSchema::resolve(&args.artifact) {
        Ok(schema) => schema,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    let graph = match ArtifactGraph::resolve(&args.artifact, &schema) {
        Ok(graph) => graph,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    let root = graph.root();
    let artifact_schema = match schema.artifact_type(&root.artifact_type) {
        Ok(schema) => schema,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    let allowed = artifact_schema
        .transitions
        .get(&root.status)
        .cloned()
        .unwrap_or_default();
    let blockers = graph.root_blockers();
    let blockers_prevent_state = !blockers.is_empty() && args.state != "blocked";
    if !allowed.contains(&args.state) || blockers_prevent_state {
        transition_blocked(root, &args.state, &allowed, &blockers, args.json);
    }

    let review_report = match review_checkpoints::checkpoint_for_transition(
        &repository,
        &root.path,
        &root.artifact_type,
        &args.state,
    ) {
        Ok(report) => report,
        Err(error) => return review_checkpoints::report_anyhow(&error, args.json),
    };
    if let Some(report) = &review_report
        && let Err(error) = review_checkpoints::report_if_blocked(report.clone(), args.json)
    {
        return Err(error);
    }

    let content = match content_with_status(&root.path, &args.state) {
        Ok(content) => content,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    let mut sources = graph
        .input_revisions
        .iter()
        .map(|(path, revision)| crate::journal::ExpectedSource {
            path: varde_workflow_core::memory::canonical_or_lexical(path),
            revision: revision.clone(),
            inventory: None,
            identity: graph.input_identities.get(path).cloned().flatten(),
        })
        .collect::<Vec<_>>();
    if let (Some(schema_path), Some(schema_revision)) = (
        schema.project_schema.as_deref(),
        schema.project_schema_revision.as_ref(),
    ) {
        sources.push(crate::journal::ExpectedSource {
            path: varde_workflow_core::memory::canonical_or_lexical(schema_path),
            revision: Some(schema_revision.clone()),
            inventory: None,
            identity: schema.project_schema_identity.clone(),
        });
    }
    let review_checkpoint = if let Some(report) = review_report.as_ref() {
        match report.consumed.plan_path.as_deref() {
            Some(plan) => {
                match crate::journal::checkpoint(&repository, plan, &report.checkpoint, report) {
                    Ok(checkpoint) => Some(checkpoint),
                    Err(error) => {
                        return report_error(&InternalError(error.to_string()), args.json);
                    }
                }
            }
            None => None,
        }
    } else {
        None
    };
    if let Err(error) = crate::journal::commit_expected_guarded(
        &lock,
        &root.path,
        &content,
        &root.revision,
        &sources,
        review_checkpoint.as_ref(),
    ) {
        if let Some(message) = crate::journal::conflict_message(&error) {
            return review_checkpoints::report_anyhow(&review_gates::conflict(message), args.json);
        }
        return report_error(&InternalError(error.to_string()), args.json);
    }
    let data = json!({
        "artifact_id": root.id,
        "previous_state": root.status,
        "state": args.state,
        "revision": varde_workflow_core::occ::version(&content),
    });
    if args.json {
        print_success(data)
    } else {
        println!("transitioned {} to {}", root.id, args.state);
        Ok(())
    }
}

fn transition_blocked(
    root: &WorkflowArtifact,
    requested: &str,
    allowed: &std::collections::BTreeSet<String>,
    blockers: &[&Blocker],
    json_output: bool,
) -> ! {
    let details = json!({
        "artifact_id": root.id,
        "current_state": root.status,
        "requested_state": requested,
        "allowed_states": allowed.iter().collect::<Vec<_>>(),
        "blockers": blockers.iter().map(|item| item.to_json()).collect::<Vec<_>>(),
    });
    if json_output {
        print_failure(
            "workflow_blocked",
            "workflow transition is not allowed",
            details,
        );
    } else {
        eprintln!("workflow transition is not allowed");
    }
    std::process::exit(4);
}
