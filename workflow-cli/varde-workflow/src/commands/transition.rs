use crate::cli::TransitionArgs;
use crate::commands::error::{InternalError, report_error};
use crate::output::{print_failure, print_success};
use crate::workflow_graph::{ArtifactGraph, Blocker, WorkflowArtifact, content_with_status};
use crate::workflow_schema::WorkflowSchema;
use anyhow::Result;
use serde_json::json;

pub fn run(args: TransitionArgs) -> Result<()> {
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

    let content = match content_with_status(&args.artifact, &args.state) {
        Ok(content) => content,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    if let Err(error) = crate::journal::commit_expected(&args.artifact, &content, &root.revision) {
        return report_error(&InternalError(error.to_string()), args.json);
    }
    let data = json!({
        "artifact_id": root.id,
        "previous_state": root.status,
        "state": args.state,
        "revision": okf_core::occ::version(&content),
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
