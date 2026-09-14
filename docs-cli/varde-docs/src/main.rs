mod cli;
mod commands {
    pub mod common;
    pub mod create;
    pub mod delete;
    pub mod error;
    pub mod input;
    pub mod lint;
    pub mod list;
    pub mod search;
    pub mod set_field;
    pub mod show;
    pub mod update;
}

use anyhow::Result;
use clap::Parser;
use cli::{Cli, Command, ConceptCommand};

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::Concept { command } => match command {
            ConceptCommand::Create(args) => commands::create::run(args)?,
            ConceptCommand::Show(args) => commands::show::run(args)?,
            ConceptCommand::Update(args) => commands::update::run(args)?,
            ConceptCommand::List(args) => commands::list::run(args)?,
            ConceptCommand::Delete(args) => commands::delete::run(args)?,
            ConceptCommand::SetField(args) => commands::set_field::run(args)?,
            ConceptCommand::Search(args) => commands::search::run(args)?,
        },
        Command::Lint(args) => commands::lint::run(args)?,
    }
    Ok(())
}
