mod artifact;
mod cli;
mod conclusion;
pub mod execution_wave;
mod execution_wave_paths;
mod execution_wave_tools;
mod output;
mod task_ownership;
mod workflow_graph;
mod workflow_schema;
mod commands {
    pub mod check_task_ownership;
    pub mod common;
    pub mod conclude;
    pub mod create;
    pub mod delete;
    pub mod distill;
    pub mod error;
    pub mod execution_wave;
    pub mod graph;
    pub mod hook;
    pub mod input;
    pub mod instructions;
    pub mod lint;
    pub mod list;
    pub mod maps;
    pub mod msg;
    pub mod now;
    pub mod owner;
    pub mod paths;
    pub mod readiness;
    pub mod search;
    pub mod set_field;
    pub mod show;
    pub mod status;
    pub mod update;
    pub mod validate;
    pub mod wake;
    pub mod watch;
    pub mod watch_block;
    pub mod watch_cache;
    pub mod watch_state;
}

use anyhow::Result;
use clap::Parser;
use cli::{Cli, Command, ConceptCommand};
use std::ffi::OsString;
use std::process::ExitCode;

pub use commands::hook::{WithinError, within};
pub use commands::instructions::{SETUP_WARNING, has_managed_block};
pub use commands::msg::{Message, commit_cursor, read_all, read_unread};
pub use commands::status::owned_plan_id;

/// The clap command tree (hidden commands included), for tools that map it.
pub fn cli_command() -> clap::Command {
    <cli::Cli as clap::CommandFactory>::command()
}

/// Run the `varde-workflow` CLI with `args` (including the program name) and
/// return its process exit code.
pub fn run(args: Vec<OsString>, io: &varde_contracts::Io<'static>) -> ExitCode {
    let deprecated_watch_alias = args.iter().any(|argument| {
        let argument = argument.to_string_lossy();
        argument == "--handoff" || argument.starts_with("--handoff=")
    });
    let cli = Cli::parse_from(args);
    if deprecated_watch_alias && matches!(&cli.command, Command::Watch(_)) {
        eprintln!("varde plan watch: --handoff is deprecated; use --notes");
    }
    match dispatch(cli, io) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("Error: {error:?}");
            ExitCode::FAILURE
        }
    }
}

fn dispatch(cli: Cli, io: &varde_contracts::Io<'static>) -> Result<()> {
    match cli.command {
        Command::Validate(args) => commands::validate::run(args)?,
        Command::CheckTaskOwnership(args) => commands::check_task_ownership::run(args)?,
        Command::ExecutionWave(args) => commands::execution_wave::run(args, io)?,
        Command::Graph(args) => commands::graph::run(args)?,
        Command::Readiness(args) => commands::readiness::run(args)?,
        Command::Status(args) => commands::status::run(args)?,
        Command::Now(args) => commands::now::run(args)?,
        Command::Owner(args) => commands::owner::run(args)?,
        Command::Msg(args) => commands::msg::run(args)?,
        Command::Watch(args) => commands::now::run_watch(args)?,
        Command::Conclude(args) => commands::conclude::run(args)?,
        Command::Distill(args) => commands::distill::run(args)?,
        Command::Concept { command } => run_concept(command)?,
        Command::Lint(args) => commands::lint::run(args)?,
        Command::Paths(args) => commands::paths::run(args)?,
        Command::Instructions(args) => commands::instructions::run(args)?,
    }
    Ok(())
}

fn run_concept(command: ConceptCommand) -> Result<()> {
    match command {
        ConceptCommand::Create(args) => commands::create::run(args),
        ConceptCommand::Show(args) => commands::show::run(args),
        ConceptCommand::Update(args) => commands::update::run(args),
        ConceptCommand::List(args) => commands::list::run(args),
        ConceptCommand::Delete(args) => commands::delete::run(args),
        ConceptCommand::SetField(args) => commands::set_field::run(args),
        ConceptCommand::Map(args) => commands::maps::run(args),
        ConceptCommand::Search(args) => commands::search::run(args),
    }
}
