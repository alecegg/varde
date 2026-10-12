mod cli;
mod diagnose;
mod friction;

use clap::{Parser, error::ErrorKind};
use std::ffi::{OsStr, OsString};
use std::process::ExitCode;
use varde_learn_core::{
    Harness as CoreHarness, LearnError, OutputHarness as CoreOutputHarness, OutputRequest,
    TriggerRequest, calibrate, run_output, run_trigger,
};

use cli::{
    AdoptionCommand, AdoptionRecordArgs, AdoptionRecurrenceArgs, CalibrateArgs, Cli,
    DiagnoseCaptureArgs, DiagnoseCommand, DiagnoseInspectArgs, DiagnoseListArgs, EvalCommand,
    FrictionAddArgs, FrictionCommand, FrictionExportArgs, FrictionImportArgs, FrictionListArgs,
    FrictionSetStatusArgs, FrictionShowArgs, Harness as CliHarness, OutputArgs,
    OutputHarness as CliOutputHarness, TopCommand, TriggerArgs,
};

/// The clap command tree (hidden commands included), for tools that map it.
pub fn cli_command() -> clap::Command {
    <cli::Cli as clap::CommandFactory>::command()
}

/// Run the `varde-learn` CLI with `args` (including the program name) and
/// return its process exit code.
pub fn run(args: Vec<OsString>, _io: &varde_contracts::Io<'_>) -> ExitCode {
    let cli = match Cli::try_parse_from(&args) {
        Ok(cli) => cli,
        Err(error) => {
            if !matches!(
                error.kind(),
                ErrorKind::DisplayHelp | ErrorKind::DisplayVersion
            ) && json_requested_for_parse_error(&args)
            {
                let error = LearnError::Usage(error.to_string());
                print_json_error(error.code(), &error.to_string());
                return ExitCode::from(2);
            }
            let _ = error.print();
            return ExitCode::from(error.exit_code() as u8);
        }
    };
    let json_errors = json_requested(&cli);
    if let Err(err) = run_cli(cli) {
        if json_errors {
            let (code, message) = err
                .downcast_ref::<LearnError>()
                .map(|error| (error.code(), error.to_string()))
                .unwrap_or_else(|| ("learn_error", format!("{err:#}")));
            print_json_error(code, &message);
        } else {
            eprintln!("error: {err:#}");
        }
        return ExitCode::from(2);
    }
    ExitCode::SUCCESS
}

fn json_requested_for_parse_error(args: &[OsString]) -> bool {
    let mut args = args.iter().skip(1);
    let Some(command) = args.next().map(OsString::as_os_str) else {
        return false;
    };
    if command == OsStr::new("eval") {
        if args.next().map(OsString::as_os_str) != Some(OsStr::new("calibrate")) {
            return false;
        }
    } else if command != OsStr::new("friction")
        && command != OsStr::new("adopt")
        && command != OsStr::new("diagnose")
    {
        return false;
    }
    args.any(|arg| arg.as_os_str() == OsStr::new("--json"))
}

fn print_json_error(code: &str, message: &str) {
    eprintln!("{}", varde_core::envelope::tool_error(code, message));
}

pub(crate) fn print_success_envelope(data: serde_json::Value, meta: serde_json::Value) {
    println!("{}", varde_core::envelope::success(data, meta,));
}

fn run_cli(cli: Cli) -> anyhow::Result<()> {
    match cli.command {
        TopCommand::Eval { command } => match command {
            EvalCommand::Trigger(args) => run_trigger_command(args),
            EvalCommand::Output(args) => run_output_command(args),
            EvalCommand::Calibrate(args) => run_calibrate_command(args),
        },
        TopCommand::Diagnose { command } => match command {
            DiagnoseCommand::Inspect(args) => diagnose::run_inspect_command(args),
            DiagnoseCommand::List(args) => diagnose::run_list_command(args),
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
        TopCommand::Eval {
            command: EvalCommand::Calibrate(CalibrateArgs { json, .. }),
        } => *json,
        TopCommand::Eval { .. } => false,
        TopCommand::Diagnose {
            command: DiagnoseCommand::Inspect(DiagnoseInspectArgs { json, .. }),
        } => *json,
        TopCommand::Diagnose {
            command: DiagnoseCommand::Capture(DiagnoseCaptureArgs { json, .. }),
        } => *json,
        TopCommand::Diagnose {
            command: DiagnoseCommand::List(DiagnoseListArgs { json, .. }),
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

fn run_calibrate_command(args: CalibrateArgs) -> anyhow::Result<()> {
    let report = calibrate(
        &args.skill_dir,
        match args.harness {
            CliOutputHarness::Codex => CoreOutputHarness::Codex,
            CliOutputHarness::Claude => CoreOutputHarness::Claude,
        },
    )?;
    if args.json {
        print_success_envelope(
            report.clone(),
            serde_json::json!({"command": "eval calibrate"}),
        );
    } else {
        println!(
            "calibration {}",
            if report["passed"] == true {
                "passed"
            } else {
                "failed"
            }
        );
    }
    if report["passed"] != true {
        std::process::exit(1);
    }
    Ok(())
}
