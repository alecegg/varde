use crate::cli::ReadinessArgs;
use crate::commands::error::{InternalError, report_error};
use crate::output::print_success;
use crate::review_checkpoints;
use crate::workflow_graph::ArtifactGraph;
use crate::workflow_schema::WorkflowSchema;
use anyhow::Result;

pub fn run(args: ReadinessArgs) -> Result<()> {
    let repository = match review_checkpoints::repository_for(&args.plan) {
        Ok(repository) => repository,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    let _lock = match crate::review_lock::ProjectLock::acquire(&repository) {
        Ok(lock) => lock,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    let result = WorkflowSchema::resolve(&args.plan).and_then(|schema| {
        let graph = ArtifactGraph::resolve(&args.plan, &schema)?;
        let mut readiness = graph.readiness_json(&schema)?;
        let root = graph.root();
        let checkpoint = match (root.artifact_type.as_str(), root.status.as_str()) {
            ("plan", "active") => Some(crate::review_gates::check_plan(
                &repository,
                &root.path,
                "resume",
            )?),
            ("plan", "backlog" | "blocked") => Some(crate::review_gates::check_plan(
                &repository,
                &root.path,
                "start",
            )?),
            ("task", "todo" | "blocked") => review_checkpoints::checkpoint_for_transition(
                &repository,
                &root.path,
                &root.artifact_type,
                "in_progress",
            )?,
            ("task", "in_progress") => review_checkpoints::checkpoint_for_transition(
                &repository,
                &root.path,
                &root.artifact_type,
                "in_progress",
            )?,
            _ => None,
        };
        let dependency_ready = readiness["ready"].as_bool().unwrap_or(false);
        readiness["planning_ready"] = serde_json::json!(dependency_ready);
        readiness["implementation_ready"] = serde_json::json!(
            dependency_ready && checkpoint.as_ref().is_none_or(|report| report.ready)
        );
        readiness["review"] = checkpoint
            .map(|report| serde_json::to_value(report).expect("review report serializes"))
            .unwrap_or(serde_json::Value::Null);
        Ok(readiness)
    });
    let data = match result {
        Ok(data) => data,
        Err(error) => return review_checkpoints::report_anyhow(&error, args.json),
    };
    if args.json {
        print_success(data)
    } else {
        println!("{}", serde_json::to_string_pretty(&data)?);
        Ok(())
    }
}
