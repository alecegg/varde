use crate::cli::GraphArgs;
use crate::commands::error::{InternalError, report_error};
use crate::output::{page_bounds, pagination_meta, print_success_with_meta};
use crate::workflow_graph::ArtifactGraph;
use crate::workflow_schema::WorkflowSchema;
use anyhow::Result;
use serde_json::{Value, json};

pub fn run(args: GraphArgs) -> Result<()> {
    let result = WorkflowSchema::resolve(&args.plan).and_then(|schema| {
        ArtifactGraph::resolve(&args.plan, &schema).and_then(|graph| graph.to_json(&schema))
    });
    let mut data = match result {
        Ok(data) => data,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    let meta = paginate_graph(&mut data, &args);
    if args.json {
        print_success_with_meta(data, meta)
    } else {
        println!("{}", serde_json::to_string_pretty(&data)?);
        if meta
            .pointer("/truncated")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            eprintln!(
                "graph output truncated; continue with --offset {}",
                args.page.offset.saturating_add(args.page.limit)
            );
        }
        Ok(())
    }
}

fn paginate_graph(data: &mut Value, args: &GraphArgs) -> Value {
    let mut sections = serde_json::Map::new();
    let mut truncated = false;
    for key in ["nodes", "edges", "blockers"] {
        let Some(items) = data.get_mut(key).and_then(Value::as_array_mut) else {
            continue;
        };
        let total = items.len();
        let (start, end) = page_bounds(total, args.page.offset, args.page.limit, args.page.all);
        let page = items[start..end].to_vec();
        *items = page;
        truncated |= end < total;
        sections.insert(
            key.to_string(),
            pagination_meta(total, start, end, args.page.limit, args.page.all)["pagination"]
                .clone(),
        );
    }
    json!({
        "truncated": truncated,
        "pagination": {
            "sections": sections,
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cli::OutputPageArgs;
    use std::path::PathBuf;

    #[test]
    fn graph_collections_are_bounded_independently() {
        let mut data = json!({
            "nodes": [0, 1, 2],
            "edges": [0, 1, 2, 3],
            "blockers": [0],
        });
        let args = GraphArgs {
            plan: PathBuf::from("plan.md"),
            page: OutputPageArgs {
                limit: 2,
                offset: 1,
                all: false,
            },
            json: true,
        };

        let meta = paginate_graph(&mut data, &args);

        assert_eq!(data["nodes"], json!([1, 2]));
        assert_eq!(data["edges"], json!([1, 2]));
        assert_eq!(data["blockers"], json!([]));
        assert_eq!(meta["truncated"], true);
        assert_eq!(meta["pagination"]["sections"]["edges"]["next_offset"], 3);
    }
}
