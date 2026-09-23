use crate::artifact;
use crate::cli::InspectArgs;
use crate::output::{print_failure, print_success};
use anyhow::Result;

pub fn run(args: InspectArgs) -> Result<()> {
    match artifact::inspect(&args.artifact) {
        Ok(envelope) if args.json => print_success(envelope.to_json()),
        Ok(envelope) => {
            println!("{} {}", envelope.artifact_type, envelope.id);
            println!("revision: {}", envelope.revision);
            println!("legacy: {}", envelope.legacy);
            Ok(())
        }
        Err(diagnostics) => {
            let details = diagnostics
                .iter()
                .map(artifact::Diagnostic::to_json)
                .collect();
            if args.json {
                print_failure(
                    "validation_failed",
                    "artifact inspection failed",
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
