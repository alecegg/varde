mod artifact;
mod cli;
mod conclusion;
mod journal;
mod output;
mod review_checkpoints;
mod review_contract;
mod review_coverage;
mod review_gates;
mod review_lock;
mod review_worktrees;
mod workflow_graph;
mod workflow_schema;
mod commands {
    pub mod common;
    pub mod conclude;
    pub mod conclusion_action;
    pub mod conclusion_retry;
    pub mod conclusion_status;
    pub mod create;
    pub mod delete;
    pub mod error;
    pub mod graph;
    pub mod input;
    pub mod lint;
    pub mod list;
    pub mod maps;
    pub mod paths;
    pub mod readiness;
    pub mod recover;
    pub mod review;
    pub mod search;
    pub mod set_field;
    pub mod show;
    pub mod spec_inventory;
    pub mod transition;
    pub mod update;
    pub mod validate;
}

use anyhow::Result;
use clap::Parser;
use cli::{Cli, Command, ConceptCommand, SpecCommand};

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::Validate(args) => commands::validate::run(args)?,
        Command::Recover(args) => commands::recover::run(args)?,
        Command::Graph(args) => commands::graph::run(args)?,
        Command::Readiness(args) => commands::readiness::run(args)?,
        Command::Transition(args) => commands::transition::run(args)?,
        Command::Conclude(args) => commands::conclude::run(args)?,
        Command::Review(args) => commands::review::run(args)?,
        Command::ConclusionStatus(args) => commands::conclusion_status::run(args)?,
        Command::ConclusionRetry(args) => commands::conclusion_retry::run(args)?,
        Command::ConclusionAction(args) => commands::conclusion_action::run(args)?,
        Command::Concept { command } => run_concept(command)?,
        Command::Lint(args) => commands::lint::run(args)?,
        Command::Paths(args) => commands::paths::run(args)?,
        Command::Spec(args) => match args.command {
            SpecCommand::Inventory(inventory) => commands::spec_inventory::run(inventory)?,
        },
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
