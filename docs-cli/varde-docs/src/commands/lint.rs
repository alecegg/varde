//! `varde-docs lint`: run the contradiction-aware bundle_lint health
//! check over a single Knowledge Bundle.
//!
//! Exit code contract: `0` when the report is empty or contains only
//! `Warning`-severity issues; non-zero when any `Error`-severity issue
//! exists. A genuine infrastructure failure (walk/read error) is a handler
//! failure and goes through `report_error` (which always exits `1`).
//!
//! This exit code is **orthogonal to the `--json` envelope**: findings are
//! data, not handler errors, so a non-zero exit in `--json` mode still
//! prints the plain issue array (`[{...}, ...]`), never the
//! `{"error": "..."}` shape `report_error` uses. A consumer must check the
//! array's contents (any `"severity": "error"` entry) to detect failure,
//! not just branch on `{"error": ...}` presence — exit code `1` here can
//! accompany a well-formed, non-error-envelope JSON payload.

use crate::cli::LintArgs;
use crate::commands::common::vault_and_bundle;
use crate::commands::error::report_error;
use anyhow::Result;
use okf_core::lint::Severity;
use okf_core::vault::lint_filtered;
use std::process::exit;

/// Run the lint check and print the report.
pub fn run(args: LintArgs) -> Result<()> {
    let (vault, bundle) = vault_and_bundle(&args);
    match lint_filtered(vault, bundle, args.okf) {
        Ok(report) => {
            if args.json {
                println!("{}", serde_json::to_string(&report.issues)?);
            } else {
                // One line per issue, in report order (`Error` before
                // `Warning`, then by path, then by check kind) — the same
                // order `--json` emits.
                for issue in &report.issues {
                    let label = match issue.severity {
                        Severity::Error => "error",
                        Severity::Warning => "warning",
                    };
                    println!("{label}: {}", issue.message);
                }
            }
            // Lint findings are not handler failures, but any Error-severity
            // issue still fails the run: exit directly rather than through
            // `report_error`, which would mislabel it as a handler error.
            if report.issues.iter().any(|i| i.severity == Severity::Error) {
                exit(1);
            }
            Ok(())
        }
        Err(err) => report_error(&err, args.json),
    }
}
