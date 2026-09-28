//! `varde-workflow lint`: run the contradiction-aware bundle_lint health
//! check over a single Knowledge Bundle.
//!
//! Exit code contract: `0` when the report is empty or contains only
//! `Warning`-severity issues; non-zero when any `Error`-severity issue
//! exists. A genuine infrastructure failure (walk/read error) is a handler
//! failure and goes through `report_error` (which always exits `1`).
//!
//! This exit code is **orthogonal to the `--json` envelope**: findings are
//! data, not handler errors, so a non-zero exit in `--json` mode still
//! prints a `negative-result` envelope whose error details contain issues.
//! Consumers can distinguish validation findings from tool failures using
//! the envelope outcome and error code.

use crate::cli::LintArgs;
use crate::commands::common::resolve_bundle;
use crate::commands::error::{InternalError, report_error};
use crate::output::{
    page_bounds, pagination_meta, print_failure_with_meta, print_success_with_meta,
};
use anyhow::Result;
use std::process::exit;
use varde_workflow_core::lint::LintOptions;
use varde_workflow_core::lint::LintReport;
use varde_workflow_core::lint::Severity;
use varde_workflow_core::lint::lint_with_options;

/// Run the lint check and print the report.
pub fn run(args: LintArgs) -> Result<()> {
    let bundle = match resolve_bundle(args.bundle.as_deref()) {
        Ok(bundle) => bundle,
        Err(err) => return report_error(&InternalError(err.to_string()), args.json),
    };
    let options = LintOptions {
        require_index: args.require_index,
    };
    match lint_with_options(&bundle, &options) {
        Ok(report) => render_report(&report, &args),
        Err(err) => report_error(&err, args.json),
    }
}

fn render_report(report: &LintReport, args: &LintArgs) -> Result<()> {
    let has_errors = report
        .issues
        .iter()
        .any(|issue| issue.severity == Severity::Error);
    if args.json {
        render_json(report, has_errors, args)?;
    } else {
        render_text(report, args);
    }
    if has_errors {
        exit(1);
    }
    Ok(())
}

fn render_json(report: &LintReport, has_errors: bool, args: &LintArgs) -> Result<()> {
    let (start, end) = page_bounds(
        report.issues.len(),
        args.page.offset,
        args.page.limit,
        args.page.all,
    );
    let issues = serde_json::to_value(&report.issues[start..end])?;
    let meta = pagination_meta(
        report.issues.len(),
        start,
        end,
        args.page.limit,
        args.page.all,
    );
    if has_errors {
        print_failure_with_meta(
            "validation_failed",
            "bundle lint found errors",
            issues,
            meta,
        );
        return Ok(());
    }
    print_success_with_meta(issues, meta)
}

fn render_text(report: &LintReport, args: &LintArgs) {
    let (start, end) = page_bounds(
        report.issues.len(),
        args.page.offset,
        args.page.limit,
        args.page.all,
    );
    for issue in &report.issues[start..end] {
        let label = match issue.severity {
            Severity::Error => "error",
            Severity::Warning => "warning",
        };
        println!("{label}: {}", issue.message);
    }
    if end < report.issues.len() {
        eprintln!(
            "showing {} of {} issues; continue with --offset {}",
            end - start,
            report.issues.len(),
            end
        );
    }
}
