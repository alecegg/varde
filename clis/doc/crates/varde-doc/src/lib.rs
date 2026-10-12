mod cli;
pub use cli::SpecInventoryArgs;
pub mod flow;
pub mod frontmatter;
pub mod spec_inventory;

use clap::Parser;
use clap::error::ErrorKind;
use cli::{
    Cli, FlowArgs, FlowCommand, FrontmatterArgs, LintArgs, SpecArgs, SpecCommand, TopCommand,
};
use serde_json::json;
use std::fmt::Write as _;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use varde_core::text_audit::{Finding, Severity, audit, expand_skill_dir};

/// The clap command tree, for tools that map it.
pub fn cli_command() -> clap::Command {
    <Cli as clap::CommandFactory>::command()
}

/// Run the `varde doc` CLI with `args` (including the program name).
pub fn run(args: Vec<std::ffi::OsString>, _io: &varde_contracts::Io<'_>) -> ExitCode {
    let cli = match Cli::try_parse_from(&args) {
        Ok(cli) => cli,
        Err(error) => {
            if matches!(
                error.kind(),
                ErrorKind::DisplayHelp | ErrorKind::DisplayVersion
            ) {
                let _ = error.print();
                return ExitCode::SUCCESS;
            }
            if let Some(code) = json_usage_error_code(&args) {
                eprintln!(
                    "{}",
                    varde_core::envelope::tool_error(code, &error.to_string())
                );
            } else {
                let _ = error.print();
            }
            return ExitCode::from(2);
        }
    };
    match cli.command {
        TopCommand::Lint(args) => run_lint(&args),
        TopCommand::Frontmatter(args) => run_frontmatter(&args),
        TopCommand::Flow(args) => run_flow(&args),
        TopCommand::Spec(args) => run_spec(args),
    }
}

fn run_spec(args: SpecArgs) -> ExitCode {
    let result = match args.command {
        SpecCommand::Inventory(args) => spec_inventory::run(args),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("Error: {error:?}");
            ExitCode::FAILURE
        }
    }
}

/// The usage-error code for a subcommand that asked for `--json` but failed
/// to parse.
fn json_usage_error_code(args: &[std::ffi::OsString]) -> Option<&'static str> {
    let mut args = args.iter().skip(1);
    let code = match args.next()?.to_str()? {
        "lint" => "doc_lint_usage",
        "frontmatter" => "doc_frontmatter_usage",
        "flow" => "doc_flow_usage",
        _ => return None,
    };
    args.any(|arg| arg == "--json").then_some(code)
}

/// Findings across every checked file.
#[derive(Debug)]
pub struct Report {
    pub findings: Vec<Finding>,
    pub files: usize,
}

impl Report {
    pub fn errors(&self) -> usize {
        self.count(Severity::Error)
    }

    pub fn warnings(&self) -> usize {
        self.count(Severity::Warn)
    }

    fn count(&self, severity: Severity) -> usize {
        self.findings
            .iter()
            .filter(|finding| finding.severity == severity)
            .count()
    }

    /// The text `check-length.py` prints: one line per finding, then a summary.
    pub fn render_text(&self) -> String {
        let mut out = String::new();
        for finding in &self.findings {
            let label = match finding.severity {
                Severity::Error => "ERROR",
                Severity::Warn => "WARN ",
            };
            let _ = writeln!(
                out,
                "{label} {}:{} {}",
                finding.path, finding.line, finding.message
            );
        }
        let _ = writeln!(
            out,
            "{} error(s), {} warning(s) across {} file(s).",
            self.errors(),
            self.warnings(),
            self.files
        );
        out
    }
}

/// Bad input: a missing path, no Markdown found, or an unreadable file.
#[derive(Debug, PartialEq, Eq)]
pub struct InputError(pub String);

fn expand(path: &Path) -> Result<Vec<PathBuf>, InputError> {
    if path.is_dir() {
        Ok(expand_skill_dir(path))
    } else if path.is_file() {
        Ok(vec![path.to_path_buf()])
    } else {
        Err(InputError(format!(
            "varde doc lint: no such file or directory: {}",
            path.display()
        )))
    }
}

/// Check `paths`: directories expand to `SKILL.md` and `references/**/*.md`;
/// files are checked as given.
pub fn lint(paths: &[PathBuf]) -> Result<Report, InputError> {
    let mut files = Vec::new();
    for path in paths {
        files.extend(expand(path)?);
    }
    if files.is_empty() {
        return Err(InputError(
            "varde doc lint: no Markdown files found".to_string(),
        ));
    }
    let mut findings = Vec::new();
    for file in &files {
        let text = fs::read_to_string(file)
            .map_err(|error| InputError(format!("varde doc lint: {}: {error}", file.display())))?;
        findings.extend(audit(&text, &file.to_string_lossy()));
    }
    Ok(Report {
        findings,
        files: files.len(),
    })
}

fn run_lint(args: &LintArgs) -> ExitCode {
    let report = match lint(&args.paths) {
        Ok(report) => report,
        Err(InputError(message)) => {
            if args.json {
                eprintln!(
                    "{}",
                    varde_core::envelope::tool_error("doc_lint_input", &message)
                );
            } else {
                eprintln!("{message}");
            }
            return ExitCode::from(2);
        }
    };
    let failed = report.errors() > 0;
    if args.json {
        println!("{}", json_envelope(&report));
    } else {
        print!("{}", report.render_text());
    }
    if failed {
        ExitCode::from(1)
    } else {
        ExitCode::SUCCESS
    }
}

fn json_envelope(report: &Report) -> serde_json::Value {
    let meta = json!({ "truncated": false });
    if report.errors() == 0 {
        return varde_core::envelope::success(json!({ "findings": report.findings }), meta);
    }
    let message = format!(
        "{} error(s), {} warning(s) across {} file(s)",
        report.errors(),
        report.warnings(),
        report.files
    );
    varde_core::envelope::negative_result(
        "doc_lint_errors",
        &message,
        json!({ "findings": report.findings }),
        meta,
    )
}

fn run_frontmatter(args: &FrontmatterArgs) -> ExitCode {
    let results = match frontmatter::check(&args.paths) {
        Ok(results) => results,
        Err(frontmatter::InputError(message)) => {
            if args.json {
                eprintln!(
                    "{}",
                    varde_core::envelope::tool_error("doc_frontmatter_input", &message)
                );
            } else {
                eprintln!("{message}");
            }
            return ExitCode::from(2);
        }
    };
    let failed = results.iter().filter(|result| !result.ok()).count();
    if args.json {
        println!("{}", frontmatter_envelope(&results, failed));
    } else {
        print!("{}", frontmatter::render_text(&results));
    }
    if failed > 0 {
        ExitCode::from(1)
    } else {
        ExitCode::SUCCESS
    }
}

fn frontmatter_envelope(results: &[frontmatter::SkillResult], failed: usize) -> serde_json::Value {
    let meta = json!({ "truncated": false });
    let data = json!({ "results": results.iter().map(frontmatter::SkillResult::to_json).collect::<Vec<_>>() });
    if failed == 0 {
        return varde_core::envelope::success(data, meta);
    }
    let message = format!(
        "{failed} of {} skill(s) failed frontmatter validation",
        results.len()
    );
    varde_core::envelope::negative_result("doc_frontmatter_failed", &message, data, meta)
}

/// Analyze every skill directory, stopping at the first that is not one.
fn analyze_all(paths: &[PathBuf]) -> Result<Vec<flow::Analysis>, InputError> {
    paths
        .iter()
        .map(|path| {
            flow::analyze(path).map_err(|error| {
                let reason = if error.kind() == std::io::ErrorKind::NotFound {
                    format!("not a skill directory: {}", path.display())
                } else {
                    format!("{}: {error}", path.display())
                };
                InputError(format!("varde doc flow: {reason}"))
            })
        })
        .collect()
}

/// `path` as Python's `Path` prints it: no `.` components.
fn plain_path(path: &Path) -> PathBuf {
    path.components()
        .filter(|part| *part != std::path::Component::CurDir)
        .collect()
}

fn run_flow(args: &FlowArgs) -> ExitCode {
    if let Some(FlowCommand::Ledger(ledger)) = &args.command {
        return flow::ledger::run(ledger);
    }
    let skills = match analyze_all(&args.paths) {
        Ok(skills) => skills,
        Err(InputError(message)) => return flow_input_error(args, &message),
    };
    if args.write || args.check {
        return flow_files(args, &skills);
    }
    let failed = skills
        .iter()
        .any(|skill| !skill.findings.missing.is_empty());
    if args.json {
        println!("{}", flow_envelope(&skills, failed));
    } else {
        let render = if args.mermaid {
            flow::mermaid
        } else {
            flow::text_report
        };
        let reports: Vec<String> = skills.iter().map(render).collect();
        println!("{}", reports.join("\n\n"));
    }
    if failed {
        ExitCode::from(1)
    } else {
        ExitCode::SUCCESS
    }
}

fn flow_input_error(args: &FlowArgs, message: &str) -> ExitCode {
    if args.json {
        eprintln!(
            "{}",
            varde_core::envelope::tool_error("doc_flow_input", message)
        );
    } else {
        eprintln!("{message}");
    }
    ExitCode::from(2)
}

/// `--write` and `--check`: one FLOW.md per skill, beside its SKILL.md.
fn flow_files(args: &FlowArgs, skills: &[flow::Analysis]) -> ExitCode {
    let mut stale = 0;
    for (path, skill) in args.paths.iter().zip(skills) {
        let target = plain_path(&path.join("FLOW.md"));
        let doc = flow::flow_doc(skill);
        if args.write {
            if let Err(error) = fs::write(&target, doc) {
                let message = format!("varde doc flow: {}: {error}", target.display());
                return flow_input_error(args, &message);
            }
        } else if fs::read_to_string(&target).ok().as_deref() != Some(doc.as_str()) {
            stale += 1;
            println!(
                "stale: {} (run varde doc flow --write {})",
                target.display(),
                plain_path(path).display()
            );
        }
    }
    if stale > 0 {
        ExitCode::from(1)
    } else {
        ExitCode::SUCCESS
    }
}

/// `data` is the list `skill-flow.py --json` prints. Serialization keeps
/// non-ASCII text as-is where Python escapes it; both are the same JSON value.
fn flow_envelope(skills: &[flow::Analysis], failed: bool) -> serde_json::Value {
    let meta = json!({ "truncated": false });
    let data = json!(skills);
    if !failed {
        return varde_core::envelope::success(data, meta);
    }
    let missing: usize = skills.iter().map(|s| s.findings.missing.len()).sum();
    let message = format!("{missing} missing file(s) across {} skill(s)", skills.len());
    varde_core::envelope::negative_result("doc_flow_missing", &message, data, meta)
}
