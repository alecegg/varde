//! `varde setup migrate-session-notes` for existing working stores.

use clap::{Arg, ArgAction, Command};
use serde::Serialize;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use varde_workflow_core::memory::{
    MemoryPaths, SessionNotesConflict, SessionNotesMove, SessionNotesSkip, migrate_session_notes,
};

#[derive(Default, Serialize)]
struct Report {
    moved: Vec<SessionNotesMove>,
    skipped: Vec<SessionNotesSkip>,
    conflicts: Vec<SessionNotesConflict>,
}

pub fn command() -> Command {
    Command::new("migrate-session-notes")
        .bin_name("varde setup migrate-session-notes")
        .about("Move legacy handoff files into session-notes")
        .arg(
            Arg::new("dry-run")
                .long("dry-run")
                .action(ArgAction::SetTrue)
                .help("Print the move list without writing changes"),
        )
        .arg(
            Arg::new("json")
                .long("json")
                .action(ArgAction::SetTrue)
                .help("Print a JSON migration and rollback manifest"),
        )
        .arg(
            Arg::new("all-projects")
                .long("all-projects")
                .action(ArgAction::SetTrue)
                .help("Migrate every project working store under agent-memory/projects"),
        )
        .arg(
            Arg::new("include-live")
                .long("include-live")
                .action(ArgAction::SetTrue)
                .help("Include session notes modified in the last 10 minutes"),
        )
}

pub fn run(args: Vec<std::ffi::OsString>) -> ExitCode {
    let matches = match command().try_get_matches_from(args) {
        Ok(matches) => matches,
        Err(error) => {
            let code = error.exit_code();
            let _ = error.print();
            return ExitCode::from(code as u8);
        }
    };

    match migrate(
        matches.get_flag("dry-run"),
        matches.get_flag("all-projects"),
        matches.get_flag("include-live"),
    ) {
        Ok((report, conflicts)) => {
            if matches.get_flag("json") {
                match serde_json::to_string(&report) {
                    Ok(json) => println!("{json}"),
                    Err(error) => {
                        eprintln!("migrate-session-notes: could not serialize report: {error}");
                        return ExitCode::from(1);
                    }
                }
            } else {
                print_report(&report, matches.get_flag("dry-run"));
            }
            if conflicts {
                ExitCode::from(1)
            } else {
                ExitCode::SUCCESS
            }
        }
        Err(error) => {
            eprintln!("migrate-session-notes: {error}");
            ExitCode::from(1)
        }
    }
}

fn migrate(
    dry_run: bool,
    all_projects: bool,
    include_live: bool,
) -> Result<(Report, bool), String> {
    let cwd =
        env::current_dir().map_err(|error| format!("cannot read current directory: {error}"))?;
    let current_working = MemoryPaths::resolve(&cwd)
        .map_err(|error| error.to_string())?
        .working
        .path;
    let stores = if all_projects {
        project_working_stores(&current_working)?
    } else {
        vec![current_working]
    };

    let mut report = Report::default();
    for working in stores {
        let migrated = migrate_session_notes(&working, dry_run, include_live)
            .map_err(|error| format!("{}: {error}", working.display()))?;
        report.moved.extend(migrated.moved);
        report.skipped.extend(migrated.skipped);
        report.conflicts.extend(migrated.conflicts);
    }
    let has_conflicts = !report.conflicts.is_empty();
    Ok((report, has_conflicts))
}

fn project_working_stores(current_working: &Path) -> Result<Vec<PathBuf>, String> {
    if current_working
        .file_name()
        .is_none_or(|name| name != "working")
    {
        return Err(invalid_all_projects_path(current_working));
    }
    let project = current_working
        .parent()
        .ok_or_else(|| invalid_all_projects_path(current_working))?;
    let projects = project
        .parent()
        .filter(|path| path.file_name().is_some_and(|name| name == "projects"))
        .ok_or_else(|| invalid_all_projects_path(current_working))?;

    let mut stores = Vec::new();
    for entry in
        fs::read_dir(projects).map_err(|error| format!("{}: {error}", projects.display()))?
    {
        let entry = entry.map_err(|error| format!("{}: {error}", projects.display()))?;
        if entry
            .file_type()
            .map_err(|error| format!("{}: {error}", entry.path().display()))?
            .is_dir()
        {
            let working = entry.path().join("working");
            if working.is_dir() {
                stores.push(working);
            }
        }
    }
    stores.sort();
    Ok(stores)
}

fn invalid_all_projects_path(current_working: &Path) -> String {
    format!(
        "cannot locate agent-memory projects from {}; expected <agent-memory>/projects/<project>/working",
        current_working.display()
    )
}

fn print_report(report: &Report, dry_run: bool) {
    let action = if dry_run { "would move" } else { "moved" };
    for item in &report.moved {
        println!("{action}: {} -> {}", item.from.display(), item.to.display());
    }
    for item in &report.skipped {
        println!("skipped: {} ({})", item.path.display(), item.reason);
    }
    for item in &report.conflicts {
        println!("conflict: {} -> {}", item.from.display(), item.to.display());
    }
    if report.moved.is_empty() && report.skipped.is_empty() && report.conflicts.is_empty() {
        println!("no session notes to migrate");
    }
}
