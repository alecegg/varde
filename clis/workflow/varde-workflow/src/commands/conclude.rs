use crate::cli::ConcludeArgs;
use crate::commands::error::{InternalError, report_error};
use crate::conclusion;
use crate::output::{print_failure, print_success};
use crate::review_checkpoints;
use crate::review_gates;
use crate::workflow_graph::ArtifactGraph;
use crate::workflow_schema::WorkflowSchema;
use anyhow::Result;
use serde_json::json;
use varde_workflow_core::memory::MemoryPaths;

pub fn run(args: ConcludeArgs) -> Result<()> {
    let repository = match review_checkpoints::repository_for(&args.plan) {
        Ok(repository) => repository,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    let lock = match crate::review_lock::ProjectLock::acquire(&repository) {
        Ok(lock) => lock,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    let plan = match args.plan.canonicalize() {
        Ok(plan) => plan,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    let schema = match WorkflowSchema::resolve(&plan) {
        Ok(schema) => schema,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    let graph = match ArtifactGraph::resolve(&plan, &schema) {
        Ok(graph) => graph,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    if graph.root().status == "completed" {
        let plan_id = graph.root().id.clone();
        if args.json {
            return print_success(json!({ "plan_id": plan_id, "already_completed": true }));
        }
        println!("already completed {plan_id}");
        return Ok(());
    }
    let graph_blockers = graph.root_blockers();
    if !graph_blockers.is_empty() {
        let details = serde_json::json!({
            "artifact_id": graph.root_id,
            "blockers": graph_blockers.iter().map(|blocker| blocker.to_json()).collect::<Vec<_>>(),
        });
        if args.json {
            crate::output::print_failure(
                "workflow_blocked",
                "plan dependencies are incomplete",
                details,
            );
        } else {
            eprintln!("error: plan dependencies are incomplete");
        }
        std::process::exit(4);
    }
    let review = match review_checkpoints::checkpoint_for_transition(
        &repository,
        &plan,
        "plan",
        "completed",
    ) {
        Ok(Some(report)) => report,
        Ok(None) => {
            return report_error(
                &InternalError("plan completion has no review checkpoint".into()),
                args.json,
            );
        }
        Err(error) => return review_checkpoints::report_anyhow(&error, args.json),
    };
    review_checkpoints::report_if_blocked(review.clone(), args.json)?;
    let checkpoint = match crate::journal::checkpoint(&repository, &plan, "complete", &review) {
        Ok(checkpoint) => checkpoint,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    let memory = match MemoryPaths::resolve(&repository) {
        Ok(memory) => memory,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    let mut prepared = match conclusion::prepare_with_memory(&plan, memory) {
        Ok(prepared) => prepared,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    prepared
        .expected_sources
        .extend(graph.input_revisions.iter().map(|(path, revision)| {
            crate::journal::ExpectedSource {
                path: varde_workflow_core::memory::canonical_or_lexical(path),
                revision: revision.clone(),
                inventory: None,
                identity: graph.input_identities.get(path).cloned().flatten(),
            }
        }));
    if let (Some(path), Some(revision)) = (
        schema.project_schema.as_deref(),
        schema.project_schema_revision.as_ref(),
    ) {
        prepared
            .expected_sources
            .push(crate::journal::ExpectedSource {
                path: varde_workflow_core::memory::canonical_or_lexical(path),
                revision: Some(revision.clone()),
                inventory: None,
                identity: schema.project_schema_identity.clone(),
            });
    }
    if let Err(error) = crate::journal::commit_many_guarded(
        &prepared.memory,
        &prepared.writes,
        &lock,
        &prepared.expected_sources,
        &checkpoint,
    ) {
        if let Some(message) = crate::journal::conflict_message(&error) {
            return review_checkpoints::report_anyhow(&review_gates::conflict(message), args.json);
        }
        return report_error(&InternalError(error.to_string()), args.json);
    }
    let data = prepared.to_json();
    if let Some(action) = std::env::var_os("VARDE_WORKFLOW_FAIL_POST_ACTION") {
        let action = action.to_string_lossy().to_string();
        if let Err(error) =
            conclusion::mark_post_failure(&prepared.memory, &prepared.plan_id, &action)
        {
            return report_error(&InternalError(error.to_string()), args.json);
        }
        if args.json {
            print_failure(
                "post_conclusion_failed",
                "core conclusion committed; qualitative enrichment failed",
                json!({ "conclusion": data, "failed_action": action }),
            );
        } else {
            eprintln!("core conclusion committed; qualitative enrichment failed: {action}");
        }
        std::process::exit(1);
    }
    if args.json {
        print_success(data)
    } else {
        println!("concluded {}", prepared.plan_id);
        Ok(())
    }
}
