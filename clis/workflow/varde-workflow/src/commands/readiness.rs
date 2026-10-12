use crate::cli::ReadinessArgs;
use crate::commands::error::{InternalError, report_error};
use crate::output::print_success;
use crate::workflow_graph::ArtifactGraph;
use crate::workflow_schema::WorkflowSchema;
use anyhow::Result;

/// Read-only readiness: a task is ready when its status is `todo` and every
/// `depends_on` task is `done`; a plan is ready when its dependencies are
/// complete. No approval or review state participates.
pub fn run(args: ReadinessArgs) -> Result<()> {
    let result = WorkflowSchema::resolve(&args.plan).and_then(|schema| {
        let graph = ArtifactGraph::resolve(&args.plan, &schema)?;
        let mut readiness = graph.readiness_json(&schema)?;
        let dependency_ready = readiness["ready"].as_bool().unwrap_or(false);
        readiness["planning_ready"] = serde_json::json!(dependency_ready);
        readiness["implementation_ready"] = serde_json::json!(dependency_ready);
        Ok(readiness)
    });
    let data = match result {
        Ok(data) => data,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    if args.json {
        print_success(data)
    } else {
        println!("{}", serde_json::to_string_pretty(&data)?);
        Ok(())
    }
}
