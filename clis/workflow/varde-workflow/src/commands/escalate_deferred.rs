use crate::cli::EscalateDeferredArgs;
use crate::commands::error::{ExitCode, InternalError, report_error};
use crate::{
    escalation, journal, output, review_checkpoints, review_gates, review_lock::ProjectLock,
};
use anyhow::Result;
use serde_json::json;
use varde_workflow_core::memory::{MemoryPaths, canonical_or_lexical};

#[derive(Debug)]
struct UsageError(String);
impl std::error::Error for UsageError {}
impl std::fmt::Display for UsageError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}
impl ExitCode for UsageError {
    fn exit_code(&self) -> i32 {
        2
    }
    fn error_code(&self) -> &'static str {
        "invalid_input"
    }
}

pub fn run(args: EscalateDeferredArgs) -> Result<()> {
    if !args.plan_dir.is_absolute() || !args.deferred_dir.is_absolute() {
        return report_error(
            &UsageError("--plan-dir and --deferred-dir must be absolute".into()),
            args.json,
        );
    }
    let result = (|| {
        let root = review_checkpoints::repository_for(&args.plan_dir)?;
        let memory = MemoryPaths::resolve(&root)?;
        escalation::validate_dirs(&memory.working.path, &args.plan_dir, &args.deferred_dir)
            .map_err(|error| anyhow::anyhow!(UsageError(error.to_string())))?;
        let lock = ProjectLock::acquire(&root)?;
        let store = ProjectLock::acquire_escalation_store(&memory.working.path)?;
        let plan = canonical_or_lexical(&args.plan_dir);
        let deferred = canonical_or_lexical(&args.deferred_dir);
        let (snapshot, sources) = escalation::capture(&plan, &deferred)?;
        let prepared = escalation::prepare(&snapshot)?;
        journal::commit_escalation_guarded(
            &memory,
            &prepared.writes,
            &lock,
            &store,
            &sources,
            &snapshot,
        )?;
        Ok::<_, anyhow::Error>(prepared)
    })();
    let prepared = match result {
        Ok(prepared) => prepared,
        Err(error) => {
            if let Some(error) = error.downcast_ref::<UsageError>() {
                return report_error(error, args.json);
            }
            if let Some(message) = journal::conflict_message(&error) {
                return review_checkpoints::report_anyhow(
                    &review_gates::conflict(message),
                    args.json,
                );
            }
            return report_error(&InternalError(error.to_string()), args.json);
        }
    };
    let escalated = prepared
        .findings
        .iter()
        .filter(|finding| finding.action == "escalated")
        .count();
    let skipped = prepared.findings.len() - escalated;
    if args.json {
        output::print_success(
            json!({"findings": prepared.findings, "summary": {"escalated": escalated, "skipped": skipped}}),
        )
    } else {
        for finding in prepared.findings {
            println!(
                "{} {} {} -> deferred {}",
                finding.action, finding.source, finding.source_finding, finding.deferred_id
            );
        }
        println!("summary: {escalated} escalated, {skipped} skipped");
        Ok(())
    }
}
