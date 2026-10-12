use clap::{Args, Parser, Subcommand, ValueEnum};
use std::path::PathBuf;

/// Check agent-facing Markdown documents.
#[derive(Debug, Parser)]
#[command(name = "varde doc", version)]
pub struct Cli {
    #[command(subcommand)]
    pub command: TopCommand,
}

#[derive(Debug, Subcommand)]
pub enum TopCommand {
    /// Check skill Markdown for long prose units, sections and layout problems; a glob over a non-skill directory aborts.
    Lint(LintArgs),
    /// Validate SKILL.md frontmatter against the agentskills.io spec; does not check body layout.
    Frontmatter(FrontmatterArgs),
    /// Map how a skill loads its files: routes, token costs, structure and findings; --check verifies FLOW.md freshness.
    Flow(FlowArgs),
    /// Inspect specification source inventory and its verified cache.
    Spec(SpecArgs),
}

#[derive(Debug, Args)]
pub struct SpecArgs {
    #[command(subcommand)]
    pub command: SpecCommand,
}

#[derive(Debug, Subcommand)]
pub enum SpecCommand {
    /// Classify domain specifications against current repository sources.
    Inventory(SpecInventoryArgs),
}

#[derive(Debug, Args)]
pub struct SpecInventoryArgs {
    #[arg(long)]
    pub repository: PathBuf,
    #[arg(long)]
    pub knowledge: PathBuf,
    #[arg(long)]
    pub working: PathBuf,
    /// Force full source and provenance validation.
    #[arg(long)]
    pub refresh: bool,
    /// Record inspected paths as non-architecture inputs at their current content hash.
    #[arg(long = "acknowledge-architecture-path")]
    pub acknowledge_architecture_paths: Vec<PathBuf>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct LintArgs {
    /// Skill directories (SKILL.md plus references/**/*.md) or Markdown files
    #[arg(required = true, value_name = "PATH")]
    pub paths: Vec<PathBuf>,
    /// Print the shared JSON envelope instead of text
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct FrontmatterArgs {
    /// Skill directories, SKILL.md files, or directories of skill directories
    #[arg(required = true, value_name = "PATH")]
    pub paths: Vec<PathBuf>,
    /// Print the shared JSON envelope instead of text
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
#[command(subcommand_negates_reqs = true)]
pub struct FlowArgs {
    #[command(subcommand)]
    pub command: Option<FlowCommand>,
    /// Skill directories (each holds a SKILL.md)
    #[arg(required = true, value_name = "SKILL_DIR")]
    pub paths: Vec<PathBuf>,
    /// Print a Mermaid diagram per skill
    #[arg(long, conflicts_with_all = ["json", "write", "check"])]
    pub mermaid: bool,
    /// Print the shared JSON envelope; `data` is the list of per-skill analyses
    #[arg(long, conflicts_with_all = ["mermaid", "write", "check"])]
    pub json: bool,
    /// Write each skill's FLOW.md
    #[arg(long, conflicts_with_all = ["mermaid", "json", "check"])]
    pub write: bool,
    /// Exit 1 when a skill's FLOW.md is missing or stale
    #[arg(long, conflicts_with_all = ["mermaid", "json", "write"])]
    pub check: bool,
}

#[derive(Debug, Subcommand)]
pub enum FlowCommand {
    /// Hash, validate, score or check a decision ledger
    Ledger(LedgerArgs),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
pub enum LedgerAction {
    /// Rewrite each decision's hash from its cited lines
    Hash,
    /// Report ledger problems (exit 1 if any)
    Validate,
    /// Print cyclomatic and cognitive scores
    Score,
    /// Report decisions whose cited lines changed or moved (exit 1 if any)
    Check,
}

#[derive(Debug, Args)]
pub struct LedgerArgs {
    pub action: LedgerAction,
    /// The ledger JSON file
    #[arg(value_name = "LEDGER")]
    pub ledger: PathBuf,
    /// Directory the ledger's source paths resolve against [default: Git top level]
    #[arg(long, value_name = "DIR")]
    pub root: Option<PathBuf>,
    /// Score only the phases of this route
    #[arg(long, value_name = "NAME")]
    pub route: Option<String>,
    /// Print the shared JSON envelope instead of text
    #[arg(long)]
    pub json: bool,
}
