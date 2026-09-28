use crate::artifact;
use crate::cli::ValidateArgs;
use crate::output::{print_failure, print_success};
use anyhow::Result;
use serde_json::json;

pub fn run(args: ValidateArgs) -> Result<()> {
    match artifact::inspect(&args.artifact) {
        Ok(envelope) => {
            if args.json {
                print_success(json!({
                    "valid": true,
                    "artifact": envelope.to_json(),
                    "diagnostics": [],
                }))
            } else {
                println!("valid: {}", args.artifact.display());
                Ok(())
            }
        }
        Err(diagnostics) => {
            let details = diagnostics
                .iter()
                .map(artifact::Diagnostic::to_json)
                .collect();
            if args.json {
                print_failure(
                    "validation_failed",
                    "artifact validation failed",
                    serde_json::Value::Array(details),
                );
            } else {
                for diagnostic in diagnostics {
                    eprintln!("{}: {}", diagnostic.field, diagnostic.message);
                }
            }
            std::process::exit(4);
        }
    }
}
