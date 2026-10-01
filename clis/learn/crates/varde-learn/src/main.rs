mod cli;
mod diagnose;
mod friction;

use clap::{Parser, error::ErrorKind};
use serde_json::json;
use std::ffi::OsStr;
use varde_learn_core::{
    Harness as CoreHarness, LearnError, OutputHarness as CoreOutputHarness, OutputRequest,
    TriggerRequest, run_output, run_trigger,
};

use cli::{
    AdoptionCommand, AdoptionRecordArgs, AdoptionRecurrenceArgs, Cli, DiagnoseCaptureArgs,
    DiagnoseCommand, DiagnoseInspectArgs, EvalCommand, FrictionAddArgs, FrictionCommand,
    FrictionExportArgs, FrictionImportArgs, FrictionListArgs, FrictionSetStatusArgs,
    FrictionShowArgs, Harness as CliHarness, OutputArgs, OutputHarness as CliOutputHarness,
    TopCommand, TriggerArgs,
};

fn main() {
    let cli = match Cli::try_parse() {
        Ok(cli) => cli,
        Err(error) => {
            if matches!(
                error.kind(),
                ErrorKind::DisplayHelp | ErrorKind::DisplayVersion
            ) {
                error.exit();
            }
            if json_requested_for_parse_error() {
                let error = LearnError::Usage(error.to_string());
                print_json_error(error.code(), &error.to_string());
                std::process::exit(2);
            }
            error.exit();
        }
    };
    let json_errors = json_requested(&cli);
    if let Err(err) = run(cli) {
        if json_errors {
            let (code, message) = err
                .downcast_ref::<LearnError>()
                .map(|error| (error.code(), error.to_string()))
                .unwrap_or_else(|| ("learn_error", format!("{err:#}")));
            print_json_error(code, &message);
        } else {
            eprintln!("error: {err:#}");
        }
        std::process::exit(2);
    }
}

fn json_requested_for_parse_error() -> bool {
    let mut args = std::env::args_os().skip(1);
    if !matches!(
        args.next().as_deref(),
        Some(value)
            if value == OsStr::new("friction")
                || value == OsStr::new("adopt")
                || value == OsStr::new("diagnose")
    ) {
        return false;
    }
    args.any(|arg| arg.as_os_str() == OsStr::new("--json"))
}

fn print_json_error(code: &str, message: &str) {
    eprintln!(
        "{}",
        json!({
            "schema_version": 1,
            "envelope_version": 1,
            "ok": false,
            "outcome": "tool-error",
            "data": { "error": { "code": code, "message": message } },
            "meta": { "truncated": false },
        })
    );
}

pub(crate) fn print_success_envelope(data: serde_json::Value, meta: serde_json::Value) {
    println!(
        "{}",
        json!({
            "schema_version": 1,
            "envelope_version": 1,
            "ok": true,
            "outcome": "success",
            "data": data,
            "meta": meta,
        })
    );
}

fn run(cli: Cli) -> anyhow::Result<()> {
    match cli.command {
        TopCommand::Eval { command } => match command {
            EvalCommand::Trigger(args) => run_trigger_command(args),
            EvalCommand::Output(args) => run_output_command(args),
        },
        TopCommand::Diagnose { command } => match command {
            DiagnoseCommand::Inspect(args) => diagnose::run_inspect_command(args),
            DiagnoseCommand::Capture(args) => diagnose::run_capture_command(args),
        },
        TopCommand::Friction { command } => match command {
            FrictionCommand::List(args) => friction::run_list_command(args),
            FrictionCommand::Add(args) => friction::run_add_command(args),
            FrictionCommand::Show(args) => friction::run_show_command(args),
            FrictionCommand::SetStatus(args) => friction::run_set_status_command(args),
            FrictionCommand::Export(args) => friction::run_export_command(args),
            FrictionCommand::Import(args) => friction::run_import_command(args),
        },
        TopCommand::Adopt { command } => match command {
            AdoptionCommand::Record(args) => friction::run_adopt_record_command(args),
            AdoptionCommand::Recurrence(args) => friction::run_adopt_recurrence_command(args),
        },
    }
}

fn json_requested(cli: &Cli) -> bool {
    match &cli.command {
        TopCommand::Friction {
            command: FrictionCommand::List(FrictionListArgs { json, .. }),
        } => *json,
        TopCommand::Friction {
            command: FrictionCommand::Add(FrictionAddArgs { json, .. }),
        } => *json,
        TopCommand::Friction {
            command: FrictionCommand::Show(FrictionShowArgs { json, .. }),
        } => *json,
        TopCommand::Friction {
            command: FrictionCommand::SetStatus(FrictionSetStatusArgs { json, .. }),
        } => *json,
        TopCommand::Friction {
            command: FrictionCommand::Export(FrictionExportArgs { json, .. }),
        } => *json,
        TopCommand::Friction {
            command: FrictionCommand::Import(FrictionImportArgs { json, .. }),
        } => *json,
        TopCommand::Adopt {
            command: AdoptionCommand::Record(AdoptionRecordArgs { json, .. }),
        } => *json,
        TopCommand::Adopt {
            command: AdoptionCommand::Recurrence(AdoptionRecurrenceArgs { json, .. }),
        } => *json,
        TopCommand::Eval { .. } => false,
        TopCommand::Diagnose {
            command: DiagnoseCommand::Inspect(DiagnoseInspectArgs { json, .. }),
        } => *json,
        TopCommand::Diagnose {
            command: DiagnoseCommand::Capture(DiagnoseCaptureArgs { json, .. }),
        } => *json,
    }
}

fn run_trigger_command(args: TriggerArgs) -> anyhow::Result<()> {
    let harness = match args.harness {
        CliHarness::Claude => CoreHarness::Claude,
        CliHarness::Opencode => CoreHarness::Opencode,
        CliHarness::Codex => CoreHarness::Codex,
    };

    let request = TriggerRequest {
        skill_name: args.skill_name,
        queries_path: args.queries,
        harness,
        runs: args.runs,
        timeout_seconds: args.timeout_seconds,
        skill_path: args.skill_path,
    };

    let report = run_trigger(&request)?;
    for line in &report.fail_lines {
        println!("{line}");
    }
    println!("{}", report.summary_line);
    if report.failed {
        std::process::exit(1);
    }
    Ok(())
}

fn run_output_command(args: OutputArgs) -> anyhow::Result<()> {
    let request = OutputRequest {
        skill_dir: args.skill_dir,
        harness: match args.harness {
            CliOutputHarness::Codex => CoreOutputHarness::Codex,
            CliOutputHarness::Claude => CoreOutputHarness::Claude,
        },
        model: args.model,
        judge_model: args.judge_model,
        runs: args.runs,
        iteration: args.iteration,
        workspace: args.workspace,
        eval_ids: args.eval,
        timeout_seconds: args.timeout_seconds,
        sandbox_dir: args.sandbox_dir,
        no_baseline: args.no_baseline,
    };

    let report = run_output(&request)?;
    for record in &report.records {
        println!(
            "{} {} run-{}: {}",
            record.eval_id,
            record.config.as_str(),
            record.run,
            record.outcome.as_str()
        );
    }
    println!(
        "eval output: {} runs written to {}",
        report.records.len(),
        report.iteration_dir.display()
    );
    println!(
        "benchmark -> {}",
        report.iteration_dir.join("benchmark.json").display()
    );
    Ok(())
}
