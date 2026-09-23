use crate::cli::ReadinessArgs;
use crate::commands::error::{InternalError, report_error};
use crate::output::print_success;
use crate::workflow_graph::ArtifactGraph;
use crate::workflow_schema::WorkflowSchema;
use anyhow::Result;

pub fn run(args: ReadinessArgs) -> Result<()> {
    let result = WorkflowSchema::resolve(&args.plan).and_then(|schema| {
        ArtifactGraph::resolve(&args.plan, &schema).and_then(|graph| graph.readiness_json(&schema))
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
